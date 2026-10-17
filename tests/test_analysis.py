from datetime import date
from decimal import Decimal

from app.services.analysis import LEDGERS, ageing, month_key, monthly, pct, _sum_cols


def test_pct_rounds_half_up_and_handles_zero():
    assert pct(1, 3) == Decimal("33.33") and pct(1, 8) == Decimal("12.50") and pct(5, 0) is None
    assert pct(1, 20000) == Decimal("0.01")  # 0.005% rounds half-up


def test_months_follow_the_business_year():
    assert month_key(date(2026, 10, 1)) == "Oct" and month_key(date(2027, 1, 5)) == "Jan" and month_key(date(2027, 9, 30)) == "Sep"


def test_monthly_sums_in_october_to_september_order_and_skips_empty_months():
    rows = monthly([(date(2027, 2, 1), 5), (date(2026, 11, 3), 10), (date(2027, 2, 20), 7), (date(2026, 10, 2), 1)])
    assert rows == [("Oct", 1), ("Nov", 10), ("Feb", 12)]


def test_ageing_buckets_only_outstanding_amounts():
    today = date(2026, 12, 31)
    dues = [(date(2027, 1, 5), 100), (date(2026, 12, 31), 10), (date(2026, 12, 25), 20), (date(2026, 12, 1), 30), (date(2026, 10, 15), 40), (date(2026, 6, 1), 50), (date(2026, 1, 1), -5), (date(2026, 1, 1), 0)]
    assert dict(ageing(dues, today)) == {"Not yet due": 110, "1-7 days late": 20, "8-30 days late": 30, "31-90 days late": 40, "Over 90 days late": 50}


def test_sum_cols_totals_only_the_given_columns():
    assert _sum_cols([["a", 1, 2.5, 10], ["b", 2, 3, 20]], [1, 3]) == ["Total", 3, "", 30]
    assert _sum_cols([], [1]) is None


def test_every_ledger_has_a_report_builder():
    from app.services.analysis import BUILDERS

    assert set(LEDGERS) == set(BUILDERS) == {"farmer", "truck", "labour_group", "bag_supplier", "broker", "industry"}
