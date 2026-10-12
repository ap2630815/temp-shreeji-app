"""Money received from industries: overview, industry account, receipts and vouchers."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response
from fastapi_csrf_protect import CsrfProtect
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.formkit import GENERIC_ERROR, YEAR_LOCKED, form_context, normalize_fields, read_form, today
from app.api.masters_config import F, run_validation
from app.api.payments import METHOD_OPTIONS, PDF_HEADERS
from app.core.db import get_db
from app.core.pdf import render_pdf
from app.core.templating import render, render_with_csrf
from app.models import Industry, Receipt, ReceiptAllocation, User
from app.services import receivables as svc
from app.services.payables import PaymentError
from app.services.years import YearLockedError

router = APIRouter()


class ReceiptIn(BaseModel):
    receipt_date: date
    amount: Annotated[int, Field(gt=0, le=1_000_000_000)]
    method: Literal["cash", "cheque", "upi", "bank"]
    payer_name: Annotated[str, Field(max_length=200)] | None = None
    reference_no: Annotated[str, Field(max_length=60)] | None = None
    note: str | None = None


def receipt_fields() -> list[F]:
    return [
        F("receipt_date", "Date received", "મળ્યાની તારીખ", kind="date", required=True),
        F("amount", "Amount (₹)", "રકમ (₹)", kind="int", required=True,
          help=("Settles the oldest weighed bilty first", "સૌથી જૂની તોલાયેલી બિલ્ટી પહેલા ચૂકવાશે")),
        F("method", "Method", "રીત", kind="select", required=True, options=METHOD_OPTIONS),
        F("payer_name", "Paid by (person)", "આપનાર (વ્યક્તિ)"),
        F("reference_no", "Cheque / UPI / bank reference", "ચેક / UPI બેંક રેફરન્સ", max_length=60, help=("Required unless cash", "રોકડ સિવાય જરૂરી")),
        F("note", "Note", "નોંધ", kind="textarea"),
    ]


async def _industry(db: AsyncSession, industry_id: int) -> Industry:
    industry = await db.get(Industry, industry_id)
    if industry is None:
        raise HTTPException(404)
    return industry


async def account_data(db: AsyncSession, industry_id: int) -> dict:
    industry = await _industry(db, industry_id)
    views = await svc.bilty_views(db, industry_id)
    return dict(industry=industry, views=views, receipts=await svc.receipts_of(db, industry_id), summary=svc.summarize(views), today=today())


# ------------------------------------------------------------------ overview

@router.get("/receivables", response_class=HTMLResponse)
async def overview(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    per: dict[int, list] = {}
    for v in await svc.bilty_views(db):
        per.setdefault(v.bilty.trip.industry_id, []).append(v)
    industries = {i.id: i for i in (await db.scalars(select(Industry).where(Industry.id.in_(per)))).all()} if per else {}
    rows = sorted(((industries[i], svc.summarize(vs)) for i, vs in per.items()), key=lambda r: (-r[1]["due"], r[0].name))
    totals = {k: sum(s[k] for _, s in rows) for k in ("trucks", "awaiting_weight", "billed", "received", "due")}
    return render_with_csrf(request, csrf, "receivables.html", user=user, rows=rows, totals=totals)


# ------------------------------------------------------------------ account

@router.get("/industries/{industry_id}/account", response_class=HTMLResponse)
async def account_page(request: Request, industry_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    return render_with_csrf(request, csrf, "industry_account.html", user=user, **await account_data(db, industry_id))


@router.get("/industries/{industry_id}/account.pdf")
async def account_pdf(industry_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    pdf = await run_in_threadpool(render_pdf, "print/industry_account.html", **await account_data(db, industry_id))
    return Response(pdf, media_type="application/pdf", headers=PDF_HEADERS)


# ------------------------------------------------------------------ receive

def _ctx(industry: Industry, fields, values, errors):
    return form_context(
        fields=fields, values=values, errors=errors, action=f"/industries/{industry.id}/receive",
        heading=(f"Receive from {industry.name}", f"{industry.name} પાસેથી પ્રાપ્તિ"), back_url=f"/industries/{industry.id}/account", industry=industry,
    )


@router.get("/industries/{industry_id}/receive", response_class=HTMLResponse)
async def receive_page(request: Request, industry_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    industry = await _industry(db, industry_id)
    summary = svc.summarize(await svc.bilty_views(db, industry_id))
    values = dict(receipt_date=today().isoformat(), method="bank", payer_name=industry.owner_name, amount=str(summary["due"]) if summary["due"] else "")
    return render_with_csrf(request, csrf, "receive_form_page.html", user=user, summary=summary, **_ctx(industry, receipt_fields(), values, {}))


@router.post("/industries/{industry_id}/receive", response_class=HTMLResponse)
async def receive(request: Request, industry_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    industry = await _industry(db, industry_id)
    fields = receipt_fields()
    raw = await read_form(request)
    rerender = lambda errs: render(request, "partials/master_form.html", **_ctx(industry, fields, raw, errs))  # noqa: E731
    clean, errors = run_validation(ReceiptIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    if clean["method"] != "cash" and not clean["reference_no"]:
        return rerender({"reference_no": ("Required unless cash", "રોકડ સિવાય જરૂરી")})
    try:
        receipt = await svc.record_receipt(db, user, industry_id, clean)
    except YearLockedError as exc:
        return rerender({"receipt_date": YEAR_LOCKED(exc.label)})
    except PaymentError as exc:
        return rerender({exc.field: exc.message})
    receipt_id = receipt.id
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return rerender({"amount": GENERIC_ERROR})
    return Response(status_code=204, headers={"HX-Redirect": f"/receipts/{receipt_id}"})


# ------------------------------------------------------------------ voucher

async def voucher_data(db: AsyncSession, receipt_id: int) -> dict:
    receipt = await db.get(Receipt, receipt_id)
    if receipt is None:
        raise HTTPException(404)
    by_id = {v.bilty.id: v for v in await svc.bilty_views(db, receipt.industry_id)}
    ids = [a.bilty_id for a in receipt.allocations]
    rows = await db.execute(
        select(ReceiptAllocation.bilty_id, func.sum(ReceiptAllocation.amount))
        .where(ReceiptAllocation.bilty_id.in_(ids), ReceiptAllocation.receipt_id <= receipt_id).group_by(ReceiptAllocation.bilty_id)
    )
    upto = {bid: int(total) for bid, total in rows.all()}
    lines = [dict(bilty=by_id[a.bilty_id].bilty, amount=a.amount, remaining=by_id[a.bilty_id].receivable - upto[a.bilty_id]) for a in receipt.allocations]
    return dict(receipt=receipt, industry=receipt.industry, lines=lines)


@router.get("/receipts/{receipt_id}", response_class=HTMLResponse)
async def voucher_page(request: Request, receipt_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    return render_with_csrf(request, csrf, "receipt_in.html", user=user, **await voucher_data(db, receipt_id))


@router.get("/receipts/{receipt_id}/voucher.pdf")
async def voucher_pdf(receipt_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    pdf = await run_in_threadpool(render_pdf, "print/receipt_in.html", **await voucher_data(db, receipt_id))
    return Response(pdf, media_type="application/pdf", headers=PDF_HEADERS)
