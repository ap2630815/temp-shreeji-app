from decimal import Decimal

from app.models import Bilty, BrokerBooking, Brokerage, Grain, PurchaseFarmerEntry, TruckLoadLine, TruckTrip
from app.services import money


def bilty(*, rate=2000, booking_weight=100, deduction=None, rate_change=0, per_bag=10, line_bags=(), expected=None, **kw):
    """A transient bilty wired to its trip / booking / brokerage / grain, with one load line per entry in line_bags."""
    grain = Grain(booking_weight=booking_weight)
    booking = BrokerBooking(grain_rate_per_booking_weight=rate, percentage_deduction=deduction, brokerage=Brokerage(brokerage_per_bag=per_bag, grain=grain))
    trip = TruckTrip(rent_per_ton=0, rent_per_bag=0, advance_amount=0, other_payable=0, other_deduction=0, broker_booking=booking)
    trip.load_lines = [TruckLoadLine(no_of_loaded_bags=b, entry=PurchaseFarmerEntry(expected_raw_weight_per_bag=expected)) for b in line_bags]
    base = dict(any_rate_change=rate_change, total_bags_in_truck=sum(line_bags), merchant_total_weight=30_000, merchant_tare_weight=10_000,
                industry_total_weight=None, industry_tare_weight=None)
    b = Bilty(**{**base, **kw})
    b.trip = trip
    return b


# ---------------------------------------------------------------- weights
def test_weights_and_differences():
    b = bilty(industry_total_weight=29_900, industry_tare_weight=10_000)
    assert (b.merchant_net_weight, b.industry_net_weight) == (20_000, 19_900)
    assert b.total_weight_difference == -100 and b.tare_weight_difference == 0
    assert b.difference_in_delivering_weight == -100
    assert b.percentage_difference == Decimal("0.50")  # positive = the industry weighed less


def test_percentage_rounds_half_up_and_can_be_negative():
    assert bilty(industry_total_weight=29_999, industry_tare_weight=10_000).percentage_difference == Decimal("0.01")  # 1/20000 = 0.005%
    assert bilty(industry_total_weight=30_010, industry_tare_weight=10_000).percentage_difference == Decimal("-0.05")  # industry weighed more


def test_no_industry_weight_yet():
    b = bilty()
    assert b.industry_net_weight is None and b.difference_in_delivering_weight is None and b.percentage_difference is None
    assert b.receivable_amount is None and b.receivable_after_deduction is None and b.error_receivable_amount is None


def test_loading_weight_difference_uses_expected_weight_per_bag():
    b = bilty(line_bags=(100, 60), expected=125)  # expected 160 bags * 125 = 20,000 kg
    assert b.expected_total_loaded_weight == 20_000
    assert b.difference_in_loading_weight == 0 and b.average_per_bag_difference == Decimal("0.00")
    b.merchant_total_weight = 30_320  # 20,320 kg on our scale
    assert b.difference_in_loading_weight == 320 and b.average_per_bag_difference == Decimal("2.00")


def test_loading_weight_difference_unknown_without_expected_weight():
    b = bilty(line_bags=(100,), expected=None)
    assert b.expected_total_loaded_weight is None and b.difference_in_loading_weight is None and b.average_per_bag_difference is None


# ---------------------------------------------------------------- receivable
def test_receivable_uses_industry_weight_and_booking_weight():
    b = bilty(industry_total_weight=29_900, industry_tare_weight=10_000)  # 19,900 kg / 100 * 2000
    assert b.receivable_amount == 398_000 and b.receivable_after_deduction == 398_000
    assert b.estimated_amount == 400_000  # 20,000 kg at our weight
    assert b.error_receivable_amount == -2_000


def test_receivable_rate_change_and_ceil():
    b = bilty(rate=2000, rate_change=15, booking_weight=20, industry_total_weight=10_333, industry_tare_weight=10_000)
    # 333 kg / 20 * 1985 = 33,050.25 -> 33,051
    assert b.effective_rate == 1985 and b.receivable_amount == 33_051


def test_percentage_deduction_reduces_the_bill():
    b = bilty(rate=300, booking_weight=20, deduction=2.5, industry_total_weight=10_715, industry_tare_weight=10_000)
    assert b.receivable_amount == 10_725  # 715 / 20 * 300
    assert b.receivable_after_deduction == 10_457  # 10,725 * 0.975 = 10,456.875
    assert b.estimated_amount == money.receivable_after_percentage_deduction(money.receivable_amount(20_000, 20, 300, 0), 2.5)


def test_receivable_after_percentage_deduction_edges():
    assert money.receivable_after_percentage_deduction(1000, None) == 1000
    assert money.receivable_after_percentage_deduction(1000, 0) == 1000
    assert money.receivable_after_percentage_deduction(1000, 5) == 950
    assert money.receivable_after_percentage_deduction(1001, 5) == 951  # 950.95 rounds half-up


# ---------------------------------------------------------------- brokerage
def test_brokerage_is_bags_times_rate_per_bag():
    assert bilty(per_bag=12, total_bags_in_truck=150).brokerage_amount == 1_800


# ---------------------------------------------------------------- freight (truck trip total)
def trip_with(bags, **kw):
    t = TruckTrip(**{**dict(rent_per_ton=0, rent_per_bag=0, advance_amount=0, other_payable=0, other_deduction=0), **kw})
    t.load_lines = [TruckLoadLine(no_of_loaded_bags=b) for b in bags]
    return t


def test_rent_per_ton_charges_on_industry_weight():
    t = trip_with([100, 50], rent_per_ton=800)
    t.bilty = bilty(industry_total_weight=29_900, industry_tare_weight=10_000)
    assert t.bags == 150 and t.freight_by_weight == 15_920 and t.freight_by_bags == 0 and t.trip_total == 15_920


def test_rent_per_bag_charges_on_loaded_bags():
    t = trip_with([100, 50], rent_per_bag=120)
    t.bilty = bilty(industry_total_weight=29_900, industry_tare_weight=10_000)
    assert t.trip_total == 18_000


def test_freight_is_provisional_until_the_industry_weighs():
    t = trip_with([100], rent_per_ton=800)
    t.bilty = bilty()  # merchant net 20,000 kg
    assert t.freight_is_provisional and t.trip_total == 16_000
    t.bilty.industry_total_weight, t.bilty.industry_tare_weight = 29_900, 10_000
    assert not t.freight_is_provisional and t.trip_total == 15_920


def test_trip_without_bilty_has_no_weight_charge():
    t = trip_with([40], rent_per_ton=800)
    assert t.freight_weight_kg is None and t.trip_total == 0
    assert trip_with([40], rent_per_bag=25).trip_total == 1_000


def test_freight_ceils_fractional_rupees():
    t = trip_with([1], rent_per_ton=801)
    t.bilty = bilty(merchant_total_weight=10_001, merchant_tare_weight=0)
    assert t.trip_total == -(-(10_001 * 801) // 1000)


def test_total_amount_after_advance_other_payable_and_deduction_never_negative():
    t = trip_with([100], rent_per_bag=100)  # trip total 10,000
    t.advance_amount, t.other_payable, t.other_deduction = 4_000, 300, 500
    assert t.total_amount == 5_800
    t.advance_amount = 20_000
    assert t.total_amount == 0


def test_expected_total_loaded_weight_none_when_any_line_unknown():
    assert money.expected_total_loaded_weight([(10, 50), (5, 60)]) == 800
    assert money.expected_total_loaded_weight([(10, 50), (5, None)]) is None
    assert money.expected_total_loaded_weight([]) == 0
