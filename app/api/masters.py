import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi_csrf_protect import CsrfProtect
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.masters_config import DUPLICATE_MSG, SPECS, Spec, normalize, validate
from app.core.db import get_db
from app.core.templating import render, render_with_csrf
from app.models import User

router = APIRouter(prefix="/masters")

LIST_LIMIT = 300


def _spec(slug: str) -> Spec:
    spec = SPECS.get(slug)
    if spec is None:
        raise HTTPException(404)
    return spec


def _form_ctx(spec: Spec, user: User, values: dict, errors: dict, obj_id: int | None, is_owner: bool | None = None):
    # is_owner may be passed in because a rollback expires `user` and its attributes can no longer be read
    if is_owner is None:
        is_owner = user.role == "owner"
    action = f"/masters/{spec.slug}" + (f"/{obj_id}" if obj_id else "")
    fields = [f for f in spec.fields if not f.owner_only or is_owner]
    verb = ("Edit", "સુધારો") if obj_id else ("Add", "ઉમેરો")
    heading = (f"{verb[0]}: {spec.label[0]}", f"{verb[1]}: {spec.label[1]}")
    return dict(spec=spec, user=user, fields=fields, values=values, errors=errors, action=action, obj_id=obj_id,
                heading=heading, back_url=f"/masters/{spec.slug}")


def _values_of(spec: Spec, obj) -> dict:
    return {f.name: "" if getattr(obj, f.name) is None else str(getattr(obj, f.name)) for f in spec.fields}


@router.get("/{slug}", response_class=HTMLResponse)
async def list_page(
    request: Request,
    slug: str,
    q: str = "",
    user: User = Depends(current_user),
    csrf: CsrfProtect = Depends(),
    db: AsyncSession = Depends(get_db),
):
    spec = _spec(slug)
    stmt = select(spec.model).order_by(getattr(spec.model, spec.order_by)).limit(LIST_LIMIT)
    q = q.strip()
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(*(getattr(spec.model, c).ilike(like) for c in spec.search_columns)))
    rows = (await db.scalars(stmt)).all()
    ctx = dict(spec=spec, rows=rows, q=q, user=user)
    if request.headers.get("HX-Target") == "rows":
        return render(request, "partials/master_rows.html", **ctx)
    return render_with_csrf(request, csrf, "master_list.html", **ctx)


@router.get("/{slug}/new", response_class=HTMLResponse)
async def new_page(request: Request, slug: str, user: User = Depends(current_user), csrf: CsrfProtect = Depends()):
    spec = _spec(slug)
    return render_with_csrf(request, csrf, "master_form_page.html", **_form_ctx(spec, user, {}, {}, None))


@router.get("/{slug}/{obj_id}/edit", response_class=HTMLResponse)
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
    return render_with_csrf(request, csrf, "master_form_page.html", **_form_ctx(spec, user, _values_of(spec, obj), {}, obj_id))


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
            return Response(status_code=204, headers={"HX-Redirect": f"/masters/{slug}"})

    # htmx does not swap 4xx, so the re-rendered form (with errors) is returned with 200
    return render(request, "partials/master_form.html", **_form_ctx(spec, user, raw, errors, obj_id, is_owner))


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
