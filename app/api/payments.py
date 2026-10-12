"""Payments to any party (farmer, transporter, labour, bag supplier, broker), statements, receipts and dues."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi_csrf_protect import CsrfProtect
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.formkit import GENERIC_ERROR, YEAR_LOCKED, form_context, normalize_fields, read_form, today
from app.api.masters_config import MOBILE, F, run_validation
from app.core.db import get_db
from app.core.pdf import render_pdf
from app.core.templating import render, render_with_csrf
from app.models import Payment, User
from app.services import payables as pay_svc
from app.services.ledger import entry_views, totals
from app.services.payables import PARTIES, PaymentError
from app.services.years import YearLockedError

router = APIRouter()

METHOD_OPTIONS = (("cash", "Cash રોકડ"), ("cheque", "Cheque ચેક"), ("upi", "UPI"), ("bank", "Bank transfer બેંક ટ્રાન્સફર"))
PDF_HEADERS = {"Content-Disposition": "inline"}


class PaymentIn(BaseModel):
    payment_date: date
    amount: Annotated[int, Field(gt=0, le=1_000_000_000)]
    method: Literal["cash", "cheque", "upi", "bank"]
    receiver_name: Annotated[str, Field(min_length=1, max_length=200)]
    receiver_mobile: Annotated[str, Field(pattern=MOBILE)]
    reference_no: Annotated[str, Field(max_length=60)] | None = None
    note: str | None = None


def payment_fields() -> list[F]:
    return [
        F("payment_date", "Payment date", "ચુકવણીની તારીખ", kind="date", required=True),
        F("amount", "Amount (₹)", "રકમ (₹)", kind="int", required=True,
          help=("Settles the oldest dues first; partial payment is fine", "સૌથી જૂની બાકી પહેલા ચૂકવાશે; આંશિક ચુકવણી ચાલે")),
        F("method", "Method", "રીત", kind="select", required=True, options=METHOD_OPTIONS),
        F("receiver_name", "Receiver name", "લેનારનું નામ", required=True),
        F("receiver_mobile", "Receiver mobile", "લેનારનો મોબાઇલ", kind="tel", required=True, pattern=MOBILE,
          hint=("10 digits", "૧૦ અંક"), max_length=10),
        F("reference_no", "Cheque / UPI / bank reference", "ચેક / UPI બેંક રેફરન્સ", max_length=60,
          help=("Required unless cash", "રોકડ સિવાય જરૂરી")),
        F("note", "Note", "નોંધ", kind="textarea"),
    ]


async def _party(db: AsyncSession, party_type: str, party_id: int):
    party = await pay_svc.get_party(db, party_type, party_id)
    if party is None:
        raise HTTPException(404)
    return party


def party_label(party_type: str) -> tuple[str, str]:
    return PARTIES[party_type].label


# ------------------------------------------------------------------ farmer statement (purchase-specific columns)

async def farmer_statement_data(db: AsyncSession, farmer_id: int) -> dict:
    farmer = await _party(db, "farmer", farmer_id)
    views = await entry_views(db, farmer_id=farmer_id)
    now = today()
    return dict(farmer=farmer, views=views, payments=await pay_svc.payments_of(db, "farmer", farmer_id), totals=totals(views, now), today=now)


@router.get("/farmers/{farmer_id}/statement", response_class=HTMLResponse)
async def farmer_statement_page(
    request: Request, farmer_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    return render_with_csrf(request, csrf, "statement.html", user=user, **await farmer_statement_data(db, farmer_id))


@router.get("/farmers/{farmer_id}/statement.pdf")
async def farmer_statement_pdf(farmer_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    pdf = await run_in_threadpool(render_pdf, "print/statement.html", **await farmer_statement_data(db, farmer_id))
    return Response(pdf, media_type="application/pdf", headers=PDF_HEADERS)


@router.get("/farmers/{farmer_id}/pay")
async def farmer_pay_redirect(farmer_id: int, user: User = Depends(current_user)):
    return RedirectResponse(f"/pay/farmer/{farmer_id}", status_code=303)


# ------------------------------------------------------------------ generic statement

async def statement_data(db: AsyncSession, party_type: str, party_id: int) -> dict:
    party = await _party(db, party_type, party_id)
    rows = await pay_svc.load_payables(db, party_type, party_id)
    now = today()
    return dict(party=party, party_type=party_type, party_label=party_label(party_type), party_name=PARTIES[party_type].name(party),
                rows=rows, payments=await pay_svc.payments_of(db, party_type, party_id), totals=pay_svc.summarize(rows, now), today=now)


@router.get("/statements/{party_type}/{party_id}", response_class=HTMLResponse)
async def statement_page(
    request: Request, party_type: str, party_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    if party_type == "farmer":
        return RedirectResponse(f"/farmers/{party_id}/statement", status_code=303)
    return render_with_csrf(request, csrf, "statement_generic.html", user=user, **await statement_data(db, party_type, party_id))


@router.get("/statements/{party_type}/{party_id}/pdf")
async def statement_pdf(party_type: str, party_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    if party_type == "farmer":
        return RedirectResponse(f"/farmers/{party_id}/statement.pdf", status_code=303)
    pdf = await run_in_threadpool(render_pdf, "print/statement_generic.html", **await statement_data(db, party_type, party_id))
    return Response(pdf, media_type="application/pdf", headers=PDF_HEADERS)


# ------------------------------------------------------------------ pay

def _pay_ctx(party_type: str, party, fields, values, errors, summary):
    name = PARTIES[party_type].name(party)
    label = party_label(party_type)
    return form_context(
        fields=fields, values=values, errors=errors, action=f"/pay/{party_type}/{party.id}",
        heading=(f"Pay {label[0].lower()}: {name}", f"ચુકવણી ({label[1]}): {name}"),
        back_url=f"/statements/{party_type}/{party.id}", party=party, party_type=party_type, summary=summary,
    )


@router.get("/pay/{party_type}/{party_id}", response_class=HTMLResponse)
async def pay_page(
    request: Request, party_type: str, party_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    party = await _party(db, party_type, party_id)
    now = today()
    summary = pay_svc.summarize(await pay_svc.load_payables(db, party_type, party_id), now)
    name, mobile = PARTIES[party_type].receiver(party)
    values = dict(payment_date=now.isoformat(), method="cash", receiver_name=name, receiver_mobile=mobile,
                  amount=str(summary["due"]) if summary["due"] else "")
    return render_with_csrf(request, csrf, "pay_form_page.html", user=user, **_pay_ctx(party_type, party, payment_fields(), values, {}, summary))


@router.post("/pay/{party_type}/{party_id}", response_class=HTMLResponse)
async def pay(
    request: Request, party_type: str, party_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    await csrf.validate_csrf(request)
    party = await _party(db, party_type, party_id)
    fields = payment_fields()
    raw = await read_form(request)
    summary = pay_svc.summarize(await pay_svc.load_payables(db, party_type, party_id), today())

    def rerender(errs):
        return render(request, "partials/master_form.html", **_pay_ctx(party_type, party, fields, raw, errs, summary))

    clean, errors = run_validation(PaymentIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    if clean["method"] != "cash" and not clean["reference_no"]:
        return rerender({"reference_no": ("Required unless cash", "રોકડ સિવાય જરૂરી")})
    try:
        payment = await pay_svc.record_payment(db, user, party_type, party_id, clean)
    except YearLockedError as exc:
        return rerender({"payment_date": YEAR_LOCKED(exc.label)})
    except PaymentError as exc:
        return rerender({exc.field: exc.message})
    payment_id = payment.id
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return rerender({"amount": GENERIC_ERROR})
    return Response(status_code=204, headers={"HX-Redirect": f"/payments/{payment_id}"})


# ------------------------------------------------------------------ receipt

async def receipt_data(db: AsyncSession, payment_id: int) -> dict:
    payment = await db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(404)
    party = await _party(db, payment.party_type, payment.party_id)
    return dict(payment=payment, party=party, party_type=payment.party_type, party_label=party_label(payment.party_type),
                party_name=PARTIES[payment.party_type].name(party), lines=await pay_svc.payment_lines(db, payment))


@router.get("/payments/{payment_id}", response_class=HTMLResponse)
async def receipt_page(
    request: Request, payment_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    return render_with_csrf(request, csrf, "receipt.html", user=user, **await receipt_data(db, payment_id))


@router.get("/payments/{payment_id}/receipt.pdf")
async def receipt_pdf(payment_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    pdf = await run_in_threadpool(render_pdf, "print/receipt.html", **await receipt_data(db, payment_id))
    return Response(pdf, media_type="application/pdf", headers=PDF_HEADERS)


# ------------------------------------------------------------------ dues

@router.get("/dues", response_class=HTMLResponse)
async def dues_page(
    request: Request, type: str = "farmer", village: str = "", user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    if type not in PARTIES:
        raise HTTPException(404)
    now = today()
    per_party: dict[int, dict] = {}
    for p in await pay_svc.load_payables(db, type):
        if p.due <= 0:
            continue
        row = per_party.setdefault(p.party_id, dict(party_id=p.party_id, name=p.party_name, due=0, overdue=0, earliest=p.sort_key[0], items=0))
        row["due"] += p.due
        row["items"] += 1
        row["earliest"] = min(row["earliest"], p.sort_key[0])
        if p.is_overdue(now):
            row["overdue"] += p.due
    villages: list[str] = []
    if type == "farmer":
        from sqlalchemy import select
        from app.models import Farmer
        farmers = {f.id: f for f in (await db.scalars(select(Farmer).where(Farmer.id.in_(per_party)))).all()} if per_party else {}
        for pid, row in per_party.items():
            row["village"], row["mobile"] = farmers[pid].village, farmers[pid].mobile
        villages = sorted({r["village"] for r in per_party.values()})
    else:
        for pid, row in per_party.items():
            party = await pay_svc.get_party(db, type, pid)
            row["village"], row["mobile"] = "", party.mobile
    rows = [r for r in per_party.values() if not village or r["village"] == village]
    rows.sort(key=lambda r: (-r["overdue"], r["earliest"], r["name"]))
    summary = dict(due=sum(r["due"] for r in rows), overdue=sum(r["overdue"] for r in rows))
    return render_with_csrf(request, csrf, "dues.html", user=user, rows=rows, villages=villages, village=village, summary=summary,
                            today=now, type=type, parties=PARTIES)
