"""Pure money / weight formulas from 'ab needs/file'. Whole rupees and integer kg; no database access.

Rounding rules (the spec does not state them): amounts are rounded UP to the next whole rupee, except the
percentage deduction on a receivable, which is rounded half-up."""

from decimal import ROUND_HALF_UP, Decimal


def ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def payable_amount(filled_bags: int, extra_kilos: int, net_bag_weight: int, rate_per_20kg: int) -> int:
    """((filled_bags * net_bag_weight + extra_kilos) / 20) * grain_rate_per_20kg, rounded up."""
    total_kg = filled_bags * net_bag_weight + extra_kilos
    return ceil_div(total_kg * rate_per_20kg, 20)


def total_available_bags(filled_bags: int, handful_bags: int) -> int:
    return filled_bags + handful_bags


def trip_freight_by_weight(industry_net_kg: int | None, rent_per_ton: int) -> int:
    """(net kg / 1000) * rent_per_ton, rounded up."""
    return ceil_div(industry_net_kg * rent_per_ton, 1000) if industry_net_kg else 0


def trip_freight_by_bags(total_bags_in_truck: int, rent_per_bag: int) -> int:
    return total_bags_in_truck * rent_per_bag


def trip_total(industry_net_kg: int | None, total_bags_in_truck: int, rent_per_ton: int, rent_per_bag: int) -> int:
    """Exactly one of rent_per_ton / rent_per_bag is non-zero (DB check), so the sum is the larger of the two terms."""
    return trip_freight_by_weight(industry_net_kg, rent_per_ton) + trip_freight_by_bags(total_bags_in_truck, rent_per_bag)


def truck_trip_total_amount(trip_total_amount: int, advance_amount: int, other_payable: int, other_deduction: int) -> int:
    """trip_total - advance_amount + other_payable - other_deduction, never below zero."""
    return max(trip_total_amount - advance_amount + other_payable - other_deduction, 0)


def brokerage_amount(total_bags_in_truck: int, brokerage_per_bag: int) -> int:
    return total_bags_in_truck * brokerage_per_bag


def expected_total_loaded_weight(lines: list[tuple[int, int | None]]) -> int | None:
    """Sum of no_of_loaded_bags * expected_raw_weight_per_bag over the trip's load lines.
    None when any line's entry has no expected weight (so a partial sum is never shown as a total)."""
    if any(weight is None for _, weight in lines):
        return None
    return sum(bags * weight for bags, weight in lines)


def receivable_amount(industry_net_kg: int, booking_weight: int, grain_rate_per_booking_weight: int, any_rate_change: int) -> int:
    """(industry net kg / booking_weight) * (rate - any_rate_change), rounded up."""
    return ceil_div(industry_net_kg * (grain_rate_per_booking_weight - any_rate_change), booking_weight)


def receivable_after_percentage_deduction(receivable: int, percentage_deduction: float | None) -> int:
    """receivable * (1 - percentage_deduction / 100), rounded half-up to whole rupees."""
    if not percentage_deduction:
        return receivable
    factor = 1 - Decimal(str(percentage_deduction)) / 100
    return int((Decimal(receivable) * factor).quantize(Decimal(1), rounding=ROUND_HALF_UP))
