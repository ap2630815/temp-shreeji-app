from app.api.masters_config import SPECS, normalize, validate


def check(slug, raw, owner=True):
    spec = SPECS[slug]
    return validate(spec, normalize(spec, raw, include_owner_only=owner))


def test_truck_number_is_normalised():
    clean, errors = check("trucks", dict(truck_number="gj 03-ab 1234", truck_owner_name="A", truck_owner_mobile="9999999999",
                                         driver_name="B", driver_mobile="8888888888"))
    assert not errors and clean["truck_number"] == "GJ03AB1234"


def test_bad_truck_number_and_mobile_rejected():
    _, errors = check("trucks", dict(truck_number="GJ03AB12", truck_owner_name="A", truck_owner_mobile="123",
                                     driver_name="B", driver_mobile="8888888888"))
    assert set(errors) == {"truck_number", "truck_owner_mobile"}


def test_required_fields_reported():
    _, errors = check("farmers", {})
    assert {"farmer_name", "mobile", "village_id"} <= set(errors)


def test_farmer_village_is_an_integer_id():
    clean, errors = check("farmers", dict(farmer_name="X", mobile="9999999999", village_id="3"))
    assert not errors and clean["village_id"] == 3
    _, errors = check("farmers", dict(farmer_name="X", mobile="9999999999", village_id="abc"))
    assert "village_id" in errors


def test_optional_blank_becomes_none():
    clean, errors = check("farmers", dict(farmer_name="X", mobile="9999999999", village_id="1", email="", upi_number=" "))
    assert not errors and clean["email"] is None and clean["upi_number"] is None


def test_ifsc_uppercased_and_validated():
    clean, errors = check("farmers", dict(farmer_name="X", mobile="9999999999", village_id="1", ifsc_code="sbin0001234"))
    assert not errors and clean["ifsc_code"] == "SBIN0001234"
    _, errors = check("farmers", dict(farmer_name="X", mobile="9999999999", village_id="1", ifsc_code="BAD"))
    assert "ifsc_code" in errors


def test_grain_bag_and_booking_weights_must_be_allowed_sizes():
    ok, errors = check("grains", dict(grain_name="Wheat", net_bag_weight="50", booking_weight="20"))
    assert not errors and (ok["net_bag_weight"], ok["booking_weight"]) == (50, 20)
    _, errors = check("grains", dict(grain_name="Wheat", net_bag_weight="45", booking_weight="30"))
    assert {"net_bag_weight", "booking_weight"} <= set(errors)


def test_brokerage_per_bag_is_a_non_negative_int():
    _, errors = check("brokerages", dict(broker_id="1", grain_id="1", brokerage_per_bag="-5"))
    assert "brokerage_per_bag" in errors
    clean, errors = check("brokerages", dict(broker_id="1", grain_id="1", brokerage_per_bag="12"))
    assert not errors and clean["brokerage_per_bag"] == 12


def test_labour_wage_rates_required():
    _, errors = check("labour-wages", dict(labour_group_id="1", grain_id="1"))
    assert {"weighing_rate", "loading_rate", "pulling_rate", "mixing_rate"} <= set(errors)


def test_owner_only_field_ignored_for_accountant():
    spec = SPECS["farmers"]
    data = normalize(spec, dict(farmer_name="X", description="secret"), include_owner_only=False)
    assert "description" not in data


def test_every_list_column_has_a_field():
    for spec in SPECS.values():
        for col in spec.list_columns:
            spec.field(col)
