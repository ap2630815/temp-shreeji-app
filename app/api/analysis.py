"""Analysis: one report per ledger, for a business year, narrowed by the toolbar's grain / village filters."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi_csrf_protect import CsrfProtect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.formkit import today
from app.core.db import get_db
from app.core.templating import render_with_csrf
from app.models import BagSupply, Bilty, PurchaseIndividual, LabourWork, Payment, PurchaseFarmerEntry, Receipt, TruckTrip, User
from app.services import analysis
from app.services.years import allowed_years, current_year_label

router = APIRouter(prefix="/Analysis")


async def _years(db: AsyncSession, user: User) -> list[str]:
    found: set[str] = set()
    for model in (PurchaseFarmerEntry, PurchaseIndividual, TruckTrip, LabourWork, BagSupply, Bilty, Payment, Receipt):
        found |= set((await db.scalars(select(model.business_year).distinct())).all())
    return allowed_years(user, found)


@router.get("", response_class=HTMLResponse)
async def analysis_page(
    request: Request, ledger: str = "farmer", year: str = "", grain_id: int = 0, village_id: int = 0,
    user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db),
):
    if ledger not in analysis.LEDGERS:
        raise HTTPException(404)
    years = await _years(db, user)
    year = year if year in years else current_year_label()  # accountants only ever get the current year
    report = await analysis.build(db, ledger, year, grain_id, village_id, today())
    keep = "&".join(f"{k}={v}" for k, v in (("year", year), ("grain_id", grain_id or ""), ("village_id", village_id or "")) if v)
    return render_with_csrf(request, csrf, "analysis.html", user=user, report=report, ledger=ledger, ledgers=analysis.LEDGERS, year=year, years=years,
                            keep=keep, filtered=bool(grain_id or village_id))
