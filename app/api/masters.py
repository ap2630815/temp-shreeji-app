import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi_csrf_protect import CsrfProtect
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.formkit import apply_toolbar
from dataclasses import replace

from app.api.masters_config import DUPLICATE_MSG, F, SPECS, Spec, national_mobile, normalize, validate
from app.core.db import get_db
from app.core.templating import render, render_with_csrf
from app.models import Broker, Farmer, Grain, LabourGroup, User, Village

router = APIRouter(prefix="/Masters")

LIST_LIMIT = 300

# kind="fk" fields: source key -> (model, order-by column, label)
FK_SOURCES = {
    "village": (Village, Village.village_name, lambda r: r.village_name),
    "labour_group": (LabourGroup, LabourGroup.group_name, lambda r: r.group_name),
    "grain": (Grain, Grain.grain_name, lambda r: r.grain_name),
    "broker": (Broker, Broker.broker_name, lambda r: r.broker_name),
}


async def _fields(spec: Spec, db: AsyncSession, is_owner: bool) -> list[F]:
    """The spec's fields for this user, with every fk field turned into a select over its master rows."""
    out: list[F] = []
    for f in spec.fields:
        if f.owner_only and not is_owner:
            continue
        if f.kind == "fk":
            model, order, label = FK_SOURCES[f.fk]
            rows = (await db.scalars(select(model).order_by(order))).unique().all()
            f = replace(f, kind="select", options=tuple((str(r.id), label(r)) for r in rows))
        out.append(f)
    return out


def _spec(slug: str) -> Spec:
    spec = SPECS.get(slug)
    if spec is None:
        raise HTTPException(404)
    return spec


async def _form_ctx(spec: Spec, user: User, values: dict, errors: dict, obj_id: int | None, db: AsyncSession, is_owner: bool | None = None):
    # is_owner may be passed in because a rollback expires `user` and its attributes can no longer be read
    if is_owner is None:
        is_owner = user.role == "owner"
    action = f"/Masters/{spec.slug}" + (f"/{obj_id}" if obj_id else "")
    fields = await _fields(spec, db, is_owner)
    verb = ("Edit", "સુધારો") if obj_id else ("Add", "ઉમેરો")
    heading = (f"{verb[0]}: {spec.label[0]}", f"{verb[1]}: {spec.label[1]}")
    domains = await email_domains(db) if any(f.kind == "email" for f in fields) else []
    parts = await name_parts(db, spec)
    return dict(spec=spec, user=user, fields=fields, values=values, errors=errors, action=action, obj_id=obj_id,
                heading=heading, back_url=f"/Masters/{spec.slug}", email_domains=domains, name_parts=parts)


COMMON_EMAIL_DOMAINS = ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "rediffmail.com", "icloud.com")


async def email_domains(db: AsyncSession) -> list[str]:
    """Every distinct address ending already saved (most used first), then the common providers not seen yet; a new ending can still be typed."""
    rows = (await db.execute(
        select(func.lower(func.split_part(Farmer.email, "@", 2)).label("d"), func.count().label("n"))
        .where(Farmer.email.is_not(None)).group_by("d").order_by(func.count().desc(), "d")
    )).all()
    used = [d for d, _ in rows if d]
    return used + [d for d in COMMON_EMAIL_DOMAINS if d not in used]


async def name_parts(db: AsyncSession, spec: Spec) -> dict[str, list[list[str]]]:
    """For every four-part name field: the names already saved in each section (surname / name / father / grandfather), most used first,
    so a section can offer them as suggestions."""
    out: dict[str, list[list[str]]] = {}
    for f in spec.fields:
        if f.kind != "name4":
            continue
        col = getattr(spec.model, f.name)
        sections = [func.split_part(col, " ", 1), func.split_part(col, " ", 2), func.split_part(col, " ", 3),
                    func.nullif(func.regexp_replace(col, r"^\S+\s+\S+\s+\S+\s*", ""), "")]
        lists = []
        for i, expr in enumerate(sections):
            # a section is only counted for names that actually have it (the 4th: at least four words)
            has = func.split_part(col, " ", i + 1) != ""
            rows = (await db.execute(select(expr.label("v"), func.count().label("n")).where(col.is_not(None), has).group_by("v").order_by(func.count().desc(), "v").limit(200))).all()
            lists.append([v for v, _ in rows if v])
        out[f.name] = lists
    return out


def _values_of(spec: Spec, obj) -> dict:
    return {f.name: "" if getattr(obj, f.name) is None else str(getattr(obj, f.name)) for f in spec.fields}


@router.get("/{slug}", response_class=HTMLResponse)
async def list_page(
    request: Request,
    slug: str,
    q: str = "",
    village_id: int = 0,
    grain_id: int = 0,
    user: User = Depends(current_user),
    csrf: CsrfProtect = Depends(),
    db: AsyncSession = Depends(get_db),
):
    spec = _spec(slug)
    stmt = select(spec.model).order_by(getattr(spec.model, spec.order_by)).limit(LIST_LIMIT)
    model = spec.model  # the toolbar village / grain narrows any master that has one (or is one)
    for value, col, own in ((village_id, "village_id", Village), (grain_id, "grain_id", Grain)):
        if value and model is own:
            stmt = stmt.where(own.id == value)
        elif value and hasattr(model, col):
            stmt = stmt.where(getattr(model, col) == value)
    q = q.strip()
    if q:
        like = f"%{q}%"
        conds = [getattr(spec.model, c).ilike(like) for c in spec.search_columns]
        digits = national_mobile(q) if re.sub(r"\D", "", q) else ""
        if digits:  # 98765 43210 finds 9876543210
            conds += [getattr(spec.model, c).ilike(f"%{digits}%") for c in spec.search_columns if "mobile" in c or "upi" in c]
        if "truck_number" in spec.search_columns:  # GJ03AB1234 finds GJ 03 AB 1234
            conds.append(func.replace(spec.model.truck_number, " ", "").ilike(f"%{q.replace(' ', '')}%"))
        stmt = stmt.where(or_(*conds))
    rows = (await db.scalars(stmt)).all()
    ctx = dict(spec=spec, rows=rows, q=q, user=user)
    if request.headers.get("HX-Target") == "rows":
        return render(request, "partials/master_rows.html", **ctx)
    return render_with_csrf(request, csrf, "master_list.html", **ctx)


@router.get("/{slug}/New", response_class=HTMLResponse)
async def new_page(
    request: Request, slug: str, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    spec = _spec(slug)
    # the toolbar's village / grain start the matching field (still editable)
    values = apply_toolbar(request, {})
    values = {k: v for k, v in values.items() if any(f.name == k for f in spec.fields)}
    return render_with_csrf(request, csrf, "master_form_page.html", **await _form_ctx(spec, user, values, {}, None, db))


@router.get("/{slug}/{obj_id}/Edit", response_class=HTMLResponse)
async def edit_page(
    request: Request,
    slug: str,
    obj_id: int,
    user: User = Depends(current_user),
    csrf: CsrfProtect = Depends(),
    db: AsyncSession = Depends(get_db),
):
    spec = _spec(slug)
    obj = await db.get(spec.model, obj_id)
    if obj is None:
        raise HTTPException(404)
    return render_with_csrf(request, csrf, "master_form_page.html", **await _form_ctx(spec, user, {**_values_of(spec, obj), **{k: v for k, v in apply_toolbar(request, _values_of(spec, obj)).items() if any(f.name == k for f in spec.fields)}}, {}, obj_id, db))


async def _save(request: Request, slug: str, obj_id: int | None, user: User, csrf: CsrfProtect, db: AsyncSession):
    await csrf.validate_csrf(request)
    spec = _spec(slug)
    is_owner = user.role == "owner"
    raw = {k: v for k, v in (await request.form()).items() if isinstance(v, str)}
    clean, errors = validate(spec, normalize(spec, raw, include_owner_only=is_owner))

    obj = None
    if obj_id is not None:
        obj = await db.get(spec.model, obj_id)
        if obj is None:
            raise HTTPException(404)

    if not errors:
        if not is_owner:
            # owner-only fields are not on the accountant's form; never overwrite them with validator defaults
            for f in spec.fields:
                if f.owner_only:
                    clean.pop(f.name, None)
        if obj is None:
            obj = spec.model(**clean)
            db.add(obj)
        else:
            for name, value in clean.items():
                setattr(obj, name, value)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            # asyncpg detail looks like: Key (mobile)=(9999999999) already exists.
            match = re.search(r"Key \((\w+)\)", str(exc.orig))
            errors = {match.group(1) if match else spec.fields[0].name: DUPLICATE_MSG}
        else:
            return Response(status_code=204, headers={"HX-Redirect": f"/Masters/{slug}"})

    # htmx does not swap 4xx, so the re-rendered form (with errors) is returned with 200
    return render(request, "partials/master_form.html", **await _form_ctx(spec, user, raw, errors, obj_id, db, is_owner))


@router.post("/{slug}", response_class=HTMLResponse)
async def create(
    request: Request, slug: str, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    return await _save(request, slug, None, user, csrf, db)


@router.post("/{slug}/{obj_id}", response_class=HTMLResponse)
async def update(
    request: Request, slug: str, obj_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    return await _save(request, slug, obj_id, user, csrf, db)
