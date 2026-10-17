"""Business-year report: income vs costs (by document date), cash movement, outstanding both ways, stock, weight shortage."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi_csrf_protect import CsrfProtect
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.formkit import today
from app.core.db import get_db
from app.core.templating import render_with_csrf
from app.models import BagSupply, PurchaseIndividual, LabourWork, Payment, PurchaseFarmerEntry, PurchaseGroup, Receipt, TruckTrip, User
from app.services import payables as pay_svc
from app.services import receivables as rec_svc
from app.services.payables import PARTIES
from app.services.stock import stock_by_entry, stock_by_purchase_group
from app.services.years import allowed_years, current_year_label

router = APIRouter(prefix="/Reports")


async def _years(db: AsyncSession, user: User) -> list[str]:
    found: set[str] = set()
    for model in (PurchaseGroup, PurchaseIndividual, TruckTrip, Payment, Receipt):
        found |= set((await db.scalars(select(model.business_year).distinct())).all())
    return allowed_years(user, found)


@router.get("/Year", response_class=HTMLResponse)
async def year_report(request: Request, year: str = "", user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    years = await _years(db, user)
    year = year if year in years else current_year_label()
    now = today()

    # ---- income (accrual)
    views = await rec_svc.bilty_views(db, business_year=year)
    sales = rec_svc.summarize(views)
    estimated_unweighed = sum(v.bilty.estimated_amount for v in views if v.receivable is None)

    # ---- costs (accrual, by document date)
    farmer_cost = int(await db.scalar(select(func.coalesce(func.sum(PurchaseFarmerEntry.payable_amount), 0)).where(PurchaseFarmerEntry.business_year == year)))
    farmer_cost += int(await db.scalar(select(func.coalesce(func.sum(PurchaseIndividual.payable_amount), 0)).where(PurchaseIndividual.business_year == year)))
    trips = list((await db.scalars(select(TruckTrip).where(TruckTrip.business_year == year))).unique().all())
    freight_cost = sum(max(t.trip_total + t.other_payable - t.other_deduction, 0) for t in trips)
    labour = list((await db.scalars(select(LabourWork).where(LabourWork.business_year == year))).unique().all())
    labour_wages, labour_extras = sum(w.payable_amount for w in labour), sum(w.petrol + w.meal for w in labour)
    bag_cost = int(await db.scalar(select(func.coalesce(func.sum(BagSupply.payable_amount), 0)).where(BagSupply.business_year == year)))
    brokerage_cost = sum(v.bilty.brokerage_amount for v in views)
    costs = [
        (("Farmers (grain purchased)", "ખેડૂતો (ખરીદેલું અનાજ)"), farmer_cost),
        (("Transport freight", "ટ્રાન્સપોર્ટ ભાડું"), freight_cost),
        (("Labour wages", "મજૂરી"), labour_wages),
        (("Labour petrol & meals", "મજૂર પેટ્રોલ અને જમવાનું"), labour_extras),
        (("Bags", "બારદાન"), bag_cost),
        (("Brokerage", "દલાલી"), brokerage_cost),
    ]
    total_costs = sum(c for _, c in costs)
    income = sales["billed"] + estimated_unweighed

    # ---- cash (by payment/receipt date's business year)
    cash_out = {pt: int(total) for pt, total in (await db.execute(select(Payment.party_type, func.sum(Payment.amount)).where(Payment.business_year == year).group_by(Payment.party_type))).all()}
    cash_in = int(await db.scalar(select(func.coalesce(func.sum(Receipt.amount), 0)).where(Receipt.business_year == year)))

    # ---- outstanding right now (all years)
    owed = {}
    for pt in PARTIES:
        owed[pt] = pay_svc.summarize(await pay_svc.load_payables(db, pt), now)["due"]
    receivable_now = rec_svc.summarize(await rec_svc.bilty_views(db))["due"]

    # ---- stock
    infos = list((await db.scalars(select(PurchaseGroup).where(PurchaseGroup.business_year == year).order_by(PurchaseGroup.purchase_group_date, PurchaseGroup.id))).unique().all())
    stock = await stock_by_purchase_group(db, [p.id for p in infos]) if infos else {}
    year_entries = list((await db.scalars(select(PurchaseFarmerEntry).where(PurchaseFarmerEntry.business_year == year))).unique().all())
    entry_stock = await stock_by_entry(db, [e.id for e in year_entries]) if year_entries else {}

    # grain bought but not yet loaded is stock (an asset at purchase cost), not an expense of this period
    stock_value = 0
    for e in year_entries:
        s_ = entry_stock.get(e.id)
        if s_ and e.total_available_bags and s_.available > 0:
            stock_value += -(-e.payable_amount * s_.available // e.total_available_bags)
    net_costs = total_costs - stock_value

    return render_with_csrf(
        request, csrf, "report_year.html", user=user, year=year, years=years, stock_value=stock_value, net_costs=net_costs,
        sales=sales, estimated_unweighed=estimated_unweighed, income=income, costs=costs, total_costs=total_costs, net=income - net_costs,
        cash_out=cash_out, cash_out_total=sum(cash_out.values()), cash_in=cash_in, owed=owed, parties=PARTIES, receivable_now=receivable_now,
        infos=infos, stock=stock,
        ship_pct=(round(sales["short_kg"] * 100 / max(sum(v.bilty.merchant_net_weight for v in views if v.receivable is not None), 1), 2)),
    )
