from app.api.masters_config import SPECS, normalize, validate


def check(slug, raw, owner=True):
    spec = SPECS[slug]
    return validate(spec, normalize(spec, raw, include_owner_only=owner))


def test_truck_number_is_normalised():
    clean, errors = check("trucks", dict(truck_number="gj 03-ab 1234", owner_name="A", owner_mobile="9999999999",
                                         driver_name="B", driver_mobile="8888888888"))
    assert not errors and clean["truck_number"] == "GJ03AB1234"


def test_bad_truck_number_and_mobile_rejected():
    _, errors = check("trucks", dict(truck_number="GJ03AB12", owner_name="A", owner_mobile="123",
                                     driver_name="B", driver_mobile="8888888888"))
    assert set(errors) == {"truck_number", "owner_mobile"}


def test_required_fields_reported():
    _, errors = check("farmers", {})
    assert {"name", "mobile", "village"} <= set(errors)


def test_optional_blank_becomes_none():
    clean, errors = check("farmers", dict(name="X", mobile="9999999999", village="V", email="", upi_number=" "))
    assert not errors and clean["email"] is None and clean["upi_number"] is None


def test_ifsc_uppercased_and_validated():
    clean, errors = check("farmers", dict(name="X", mobile="9999999999", village="V", ifsc_code="sbin0001234"))
    assert not errors and clean["ifsc_code"] == "SBIN0001234"
    _, errors = check("farmers", dict(name="X", mobile="9999999999", village="V", ifsc_code="BAD"))
    assert "ifsc_code" in errors


def test_grain_bag_weight_must_be_allowed_size():
    ok, errors = check("grains", dict(name="Wheat", default_net_weight="50"))
    assert not errors and ok["default_net_weight"] == 50
    _, errors = check("grains", dict(name="Wheat", default_net_weight="45"))
    assert "default_net_weight" in errors


def test_broker_brokerage_non_negative_int():
    _, errors = check("brokers", dict(name="B", mobile="9999999999", brokerage_per_truck="-5"))
    assert "brokerage_per_truck" in errors
    clean, errors = check("brokers", dict(name="B", mobile="9999999999", brokerage_per_truck="1500"))
    assert not errors and clean["brokerage_per_truck"] == 1500


def test_owner_only_field_ignored_for_accountant():
    spec = SPECS["farmers"]
    data = normalize(spec, dict(name="X", description="secret"), include_owner_only=False)
    assert "description" not in data
