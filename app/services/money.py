def payable_amount(filled_bags: int, extra_kilos: int, net_weight: int, rate_per_20kg: int) -> int:
    """ceil(((bags * net_weight + kilos) / 20) * rate), in whole rupees, using integer arithmetic only."""
    total_kg = filled_bags * net_weight + extra_kilos
    return -(-(total_kg * rate_per_20kg) // 20)
