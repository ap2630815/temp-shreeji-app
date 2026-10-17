"""Owner-only list of business years (Oct-Sep). Only the current year accepts entries; earlier years close
automatically on 1 October and stay viewable by the owner."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi_csrf_protect import CsrfProtect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.db import get_db
from app.core.templating import render_with_csrf
from app.models import BagSupply, BrokerBooking, PurchaseIndividual, LabourWork, Payment, PurchaseFarmerEntry, PurchaseGroup, Receipt, TruckTrip, User
from app.services.years import allowed_years, current_year_label, year_bounds

router = APIRouter(prefix="/Years")


@router.get("", response_class=HTMLResponse)
async def years_page(request: Request, user: User = Depends(require_role("owner")), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    found: set[str] = set()
    for model in (PurchaseGroup, PurchaseFarmerEntry, PurchaseIndividual, BrokerBooking, TruckTrip, LabourWork, BagSupply, Payment, Receipt):
        found |= set((await db.scalars(select(model.business_year).distinct())).all())
    current = current_year_label()
    rows = [dict(label=y, current=y == current, bounds=year_bounds(y)) for y in allowed_years(user, found)]
    return render_with_csrf(request, csrf, "years.html", user=user, rows=rows)
