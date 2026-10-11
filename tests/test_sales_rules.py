from decimal import Decimal

from app.models import Bilty, TruckLoadLine, TruckTrip


def bilty(**kw):
    base = dict(grain_rate=2000, rate_unit_kg=100, rate_change=0, merchant_total_weight=30_000, merchant_tare_weight=10_000,
                industry_total_weight=None, industry_tare_weight=None)
    return Bilty(**{**base, **kw})


def trip(bags_by_line=(), **kw):
    t = TruckTrip(**{**dict(rent_per_ton=0, rent_per_bag=0, advance_amount=0, other_deduction=0), **kw})
    t.load_lines = [TruckLoadLine(bags=b) for b in bags_by_line]
    return t


# ---------------------------------------------------------------- weights
def test_weights_and_differences():
    b = bilty(industry_total_weight=29_900, industry_tare_weight=10_000)
    assert (b.merchant_net_weight, b.industry_net_weight) == (20_000, 19_900)
    assert (b.difference_total_weight, b.difference_tare_weight, b.difference_net_weight) == (100, 0, 100)
    assert b.percentage_difference == Decimal("0.50")


def test_percentage_rounds_half_up_and_can_be_negative():
    assert bilty(industry_total_weight=29_999, industry_tare_weight=10_000).percentage_difference == Decimal("0.01")  # 1/20000 = 0.005%
    assert bilty(industry_total_weight=30_010, industry_tare_weight=10_000).percentage_difference == Decimal("-0.05")  # industry weighed more


def test_no_industry_weight_yet():
    b = bilty()
    assert b.industry_net_weight is None and b.difference_net_weight is None and b.percentage_difference is None
    assert b.receivable_amount is None and b.error_receivable_amount is None


# ---------------------------------------------------------------- receivable
def test_receivable_uses_industry_weight_and_rate_unit():
    # 19,900 kg / 100 kg * 2000 = 398,000
    b = bilty(industry_total_weight=29_900, industry_tare_weight=10_000)
    assert b.receivable_amount == 398_000
    assert b.estimated_amount == 400_000  # 20,000 kg at our weight
    assert b.error_receivable_amount == -2_000


def test_receivable_rate_change_and_ceil():
    b = bilty(grain_rate=2000, rate_change=15, rate_unit_kg=20, industry_total_weight=10_333, industry_tare_weight=10_000)
    # 333 kg / 20 * 1985 = 33,050.25 -> 33,051
    assert b.effective_rate == 1985 and b.receivable_amount == 33_051


def test_rate_unit_20kg():
    b = bilty(grain_rate=300, rate_unit_kg=20, industry_total_weight=10_715, industry_tare_weight=10_000)
    assert b.receivable_amount == 10_725  # 715 / 20 * 300


# ---------------------------------------------------------------- freight
def test_freight_takes_the_larger_of_weight_and_bag_charge():
    t = trip([100, 50], rent_per_ton=800, rent_per_bag=20)
    t.bilty = bilty(industry_total_weight=29_900, industry_tare_weight=10_000)
    # by weight: 19.9 t * 800 = 15,920 ; by bags: 150 * 20 = 3,000
    assert t.freight == 15_920 and t.bags == 150
    t.rent_per_bag = 120  # 150 * 120 = 18,000 beats 15,920
    assert t.freight == 18_000


def test_freight_is_provisional_until_the_industry_weighs():
    t = trip([100], rent_per_ton=800)
    t.bilty = bilty()  # merchant net 20,000 kg
    assert t.freight_is_provisional and t.freight == 16_000
    t.bilty.industry_total_weight, t.bilty.industry_tare_weight = 29_900, 10_000
    assert not t.freight_is_provisional and t.freight == 15_920


def test_freight_without_bilty_falls_back_to_bag_charge():
    t = trip([40], rent_per_ton=800, rent_per_bag=25)
    assert t.freight_weight_kg is None and t.freight == 1_000


def test_freight_ceils_fractional_rupees():
    t = trip([1], rent_per_ton=801)
    t.bilty = bilty(merchant_total_weight=10_001, merchant_tare_weight=0)
    assert t.freight == -(-(10_001 * 801) // 1000)


def test_final_payment_after_advance_and_deduction_never_negative():
    t = trip([100], rent_per_ton=0, rent_per_bag=100)  # freight 10,000
    t.advance_amount, t.other_deduction = 4_000, 500
    assert t.final_payment == 5_500
    t.advance_amount = 20_000
    assert t.final_payment == 0
