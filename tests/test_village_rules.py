from datetime import date

import pytest

from app.models import PurchaseEntry
from app.services.audit import diff
from app.services.ledger import EntryView, allocate
from app.services.money import payable_amount
from app.services.years import business_year_of, year_bounds


def test_payable_whole_bags():
    # 10 bags x 50 kg = 500 kg = 25 units of 20 kg, rate 300 -> 7500
    assert payable_amount(10, 0, 50, 300) == 7500


def test_payable_with_extra_kilos():
    # 14 bags x 50 + 15 kg = 715 kg -> 35.75 units x 300 = 10725
    assert payable_amount(14, 15, 50, 300) == 10725


def test_payable_rounds_up_never_down():
    # 1 kg at rate 301 -> 301/20 = 15.05 -> 16
    assert payable_amount(0, 1, 50, 301) == 16
    assert payable_amount(0, 0, 50, 300) == 0


def test_payable_uses_integer_math_for_large_values():
    assert payable_amount(100_000, 19, 100, 1999) == -(-((100_000 * 100 + 19) * 1999) // 20)


def test_business_year_boundaries():
    assert business_year_of(date(2025, 10, 1)) == "2025-26"
    assert business_year_of(date(2026, 9, 30)) == "2025-26"
    assert business_year_of(date(2026, 10, 1)) == "2026-27"
    assert business_year_of(date(2026, 1, 15)) == "2025-26"
    assert business_year_of(date(2099, 12, 31)) == "2099-00"


def test_year_bounds():
    assert year_bounds("2025-26") == (date(2025, 10, 1), date(2026, 9, 30))


def test_allocate_oldest_first_partial_and_exact():
    dues = [(1, 1000), (2, 500), (3, 700)]
    assert allocate(1200, dues) == [(1, 1000), (2, 200)]
    assert allocate(2200, dues) == [(1, 1000), (2, 500), (3, 700)]
    assert allocate(300, dues) == [(1, 300)]


def test_allocate_skips_settled_entries():
    assert allocate(100, [(1, 0), (2, -5), (3, 400)]) == [(3, 100)]


def test_allocate_rejects_overpayment_and_non_positive():
    with pytest.raises(ValueError):
        allocate(2201, [(1, 1000), (2, 500), (3, 700)])
    with pytest.raises(ValueError):
        allocate(0, [(1, 10)])
    with pytest.raises(ValueError):
        allocate(-1, [(1, 10)])


def _view(payable, borrowing, paid, due_date):
    e = PurchaseEntry(payable_amount=payable, borrowing=borrowing, due_date=due_date)
    return EntryView(e, paid)


def test_entry_status_and_overdue():
    today = date(2026, 1, 10)
    v = _view(1000, 100, 0, date(2026, 2, 1))
    assert (v.net_payable, v.due, v.status, v.is_overdue(today)) == (900, 900, "pending", False)
    v = _view(1000, 100, 400, date(2026, 1, 1))
    assert (v.due, v.status, v.is_overdue(today)) == (500, "partial", True)
    v = _view(1000, 100, 900, date(2026, 1, 1))
    assert (v.due, v.status, v.is_overdue(today)) == (0, "paid", False)


def test_audit_diff_only_changed_fields():
    before = {"a": 1, "b": 2, "d": date(2026, 1, 1)}
    assert diff(before, {"a": 1, "b": 3, "d": date(2026, 1, 2)}) == {"b": [2, 3], "d": ["2026-01-01", "2026-01-02"]}
    assert diff(None, {"a": 1, "d": date(2026, 1, 2)}) == {"a": 1, "d": "2026-01-02"}


def test_payable_dataclass_status_and_overdue():
    from app.services.payables import Payable

    def mk(amount, paid, due_date):
        return Payable("truck_trip", 1, "transporter", 1, "T", date(2026, 1, 1), due_date, "x", amount, paid)

    today = date(2026, 2, 1)
    assert mk(1000, 0, None).status == "pending" and not mk(1000, 0, None).is_overdue(today)  # no due date -> never overdue
    assert mk(1000, 300, date(2026, 1, 15)).status == "partial" and mk(1000, 300, date(2026, 1, 15)).is_overdue(today)
    assert mk(1000, 1000, date(2026, 1, 15)).status == "paid" and not mk(1000, 1000, date(2026, 1, 15)).is_overdue(today)


def test_bilty_view_status():
    from app.models import Bilty
    from app.services.receivables import BiltyView

    def view(industry_weight, received):
        b = Bilty(grain_rate=300, rate_unit_kg=20, rate_change=0, merchant_total_weight=10_800, merchant_tare_weight=0,
                  industry_total_weight=industry_weight, industry_tare_weight=0 if industry_weight else None)
        return BiltyView(b, received)

    assert view(None, 0).status == "unweighed" and view(None, 0).due is None
    v = view(10_000, 0)  # 10,000 kg / 20 * 300 = 150,000
    assert (v.receivable, v.due, v.status) == (150_000, 150_000, "pending")
    assert view(10_000, 50_000).status == "partial" and view(10_000, 150_000).status == "paid"


# ---------------------------------------------------------------- business year closing

import asyncio
from types import SimpleNamespace

from fastapi import HTTPException

from app.services import years as years_svc


def _fake_today(monkeypatch, d):
    class FakeDate(date):
        @classmethod
        def today(cls):
            return d

    monkeypatch.setattr(years_svc, "date", FakeDate)


def test_only_current_business_year_accepts_entries(monkeypatch):
    _fake_today(monkeypatch, date(2026, 10, 12))  # current year is 2026-27
    assert asyncio.run(years_svc.assert_year_open(None, date(2026, 10, 1))) == "2026-27"
    assert asyncio.run(years_svc.assert_year_open(None, date(2027, 9, 30))) == "2026-27"
    for outside in (date(2026, 9, 30), date(2027, 10, 1), date(2023, 12, 1)):
        with pytest.raises(years_svc.YearLockedError):
            asyncio.run(years_svc.assert_year_open(None, outside))


def test_year_closes_on_first_october(monkeypatch):
    _fake_today(monkeypatch, date(2026, 9, 30))
    assert asyncio.run(years_svc.assert_year_open(None, date(2026, 9, 30))) == "2025-26"
    _fake_today(monkeypatch, date(2026, 10, 1))
    with pytest.raises(years_svc.YearLockedError):
        asyncio.run(years_svc.assert_year_open(None, date(2026, 9, 30)))


def test_only_owner_browses_past_years(monkeypatch):
    _fake_today(monkeypatch, date(2026, 10, 12))
    owner, accountant = SimpleNamespace(role="owner"), SimpleNamespace(role="accountant")
    assert years_svc.allowed_years(owner, ["2024-25", "2023-24"]) == ["2026-27", "2024-25", "2023-24"]
    assert years_svc.allowed_years(accountant, ["2024-25"]) == ["2026-27"]
    years_svc.require_year_visible(owner, "2024-25")
    years_svc.require_year_visible(accountant, "2026-27")
    with pytest.raises(HTTPException) as exc:
        years_svc.require_year_visible(accountant, "2024-25")
    assert exc.value.status_code == 403
