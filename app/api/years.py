"""Owner-only business-year lock (Oct-Sep). A locked year rejects any new or changed entry/payment dated in it."""

import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi_csrf_protect import CsrfProtect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.api.formkit import today
from app.core.db import get_db
from app.core.templating import render, render_with_csrf
from app.models import BusinessYear, Commencing, Payment, User
from app.services import audit
from app.services.years import business_year_of, year_bounds

router = APIRouter(prefix="/years")


async def _all_years(db: AsyncSession) -> list[str]:
    found = set((await db.scalars(select(Commencing.business_year))).all())
    found |= set((await db.scalars(select(Payment.business_year))).all())
    found |= set((await db.scalars(select(BusinessYear.label))).all())
    found.add(business_year_of(today()))
    return sorted(found, reverse=True)


async def _rows(db: AsyncSession) -> list[dict]:
    locked = {y.label: y for y in (await db.scalars(select(BusinessYear))).all()}
    return [dict(label=y, locked=bool(locked.get(y) and locked[y].is_locked), bounds=year_bounds(y)) for y in await _all_years(db)]


@router.get("", response_class=HTMLResponse)
async def years_page(request: Request, user: User = Depends(require_role("owner")), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    return render_with_csrf(request, csrf, "years.html", user=user, rows=await _rows(db))


@router.post("/{label}", response_class=HTMLResponse)
async def set_lock(
    request: Request,
    label: str,
    locked: int = Form(...),
    user: User = Depends(require_role("owner")),
    csrf: CsrfProtect = Depends(),
    db: AsyncSession = Depends(get_db),
):
    await csrf.validate_csrf(request)
    if not re.fullmatch(r"\d{4}-\d{2}", label) or label != business_year_of(year_bounds(label)[0]):
        raise HTTPException(404)
    row = await db.get(BusinessYear, label)
    was = bool(row and row.is_locked)
    if row is None:
        row = BusinessYear(label=label)
        db.add(row)
    row.is_locked = bool(locked)
    row.changed_by = user.id
    audit.log(db, user, "lock" if locked else "unlock", "business_years", None, {"year": label, "was_locked": was})
    await db.commit()
    return render(request, "partials/year_row.html", y=dict(label=label, locked=bool(locked), bounds=year_bounds(label)))
