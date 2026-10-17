from app.api.masters_config import SPECS, normalize, validate


def check(slug, raw, owner=True):
    spec = SPECS[slug]
    return validate(spec, normalize(spec, raw, include_owner_only=owner))


def test_truck_number_is_normalised():
    clean, errors = check("Trucks", dict(truck_number="gj 03-ab 1234", truck_owner_name="A", truck_owner_mobile="9999999999",
                                         driver_name="B", driver_mobile="8888888888"))
    assert not errors and clean["truck_number"] == "GJ 03 AB 1234"


def test_truck_number_standard_format():
    for typed, shown in (("gj01dg3345", "GJ 01 DG 3345"), ("GJ-14-X-6720", "GJ 14  X 6720"), ("GJ 14 X 6720", "GJ 14  X 6720"), ("gj14  x 6720", "GJ 14  X 6720")):
        clean, errors = check("Trucks", dict(truck_number=typed, truck_owner_name="A", truck_owner_mobile="9999999999",
                                             driver_name="B", driver_mobile="8888888888"))
        assert not errors and clean["truck_number"] == shown


def test_bad_truck_number_and_mobile_rejected():
    _, errors = check("Trucks", dict(truck_number="GJ03AB12", truck_owner_name="A", truck_owner_mobile="123",
                                     driver_name="B", driver_mobile="8888888888"))
    assert set(errors) == {"truck_number", "truck_owner_mobile"}


def test_required_fields_reported():
    _, errors = check("Farmers", {})
    assert {"farmer_name", "mobile", "village_id"} <= set(errors)


def test_farmer_village_is_an_integer_id():
    clean, errors = check("Farmers", dict(farmer_name="X Y Z", head_of_family="Self", mobile="9999999999", village_id="3"))
    assert not errors and clean["village_id"] == 3
    _, errors = check("Farmers", dict(farmer_name="X Y Z", head_of_family="Self", mobile="9999999999", village_id="abc"))
    assert "village_id" in errors


def test_optional_blank_becomes_none():
    clean, errors = check("Farmers", dict(farmer_name="X Y Z", head_of_family="Self", mobile="9999999999", village_id="1", email="", upi_number=" "))
    assert not errors and clean["email"] is None and clean["upi_number"] is None


def test_ifsc_uppercased_and_validated():
    clean, errors = check("Farmers", dict(farmer_name="X Y Z", head_of_family="Self", mobile="9999999999", village_id="1", ifsc_code="sbin0001234"))
    assert not errors and clean["ifsc_code"] == "SBIN0001234"
    _, errors = check("Farmers", dict(farmer_name="X Y Z", head_of_family="Self", mobile="9999999999", village_id="1", ifsc_code="BAD"))
    assert "ifsc_code" in errors


def test_grain_bag_and_booking_weights_must_be_allowed_sizes():
    ok, errors = check("Grains", dict(grain_name="Wheat", net_bag_weight="50", booking_weight="20"))
    assert not errors and (ok["net_bag_weight"], ok["booking_weight"]) == (50, 20)
    _, errors = check("Grains", dict(grain_name="Wheat", net_bag_weight="45", booking_weight="30"))
    assert {"net_bag_weight", "booking_weight"} <= set(errors)


def test_brokerage_per_bag_is_a_non_negative_int():
    _, errors = check("Brokerages", dict(broker_id="1", grain_id="1", brokerage_per_bag="-5"))
    assert "brokerage_per_bag" in errors
    clean, errors = check("Brokerages", dict(broker_id="1", grain_id="1", brokerage_per_bag="12"))
    assert not errors and clean["brokerage_per_bag"] == 12


def test_labour_wage_rates_required():
    _, errors = check("LabourWages", dict(labour_group_id="1", grain_id="1"))
    assert {"weighing_rate", "loading_rate", "pulling_rate", "mixing_rate"} <= set(errors)


def test_owner_only_field_ignored_for_accountant():
    spec = SPECS["Farmers"]
    data = normalize(spec, dict(farmer_name="X Y Z", head_of_family="Self", description="secret"), include_owner_only=False)
    assert "description" not in data


def test_every_list_column_has_a_field():
    for spec in SPECS.values():
        for col in spec.list_columns:
            spec.field(col)


def test_mobile_typed_with_a_space_is_stored_as_ten_digits():
    clean, errors = check("Farmers", dict(farmer_name="X Y Z", head_of_family="Self", mobile="98765 43210", village_id="1"))
    assert not errors and clean["mobile"] == "9876543210"
    _, errors = check("Farmers", dict(farmer_name="X Y Z", head_of_family="Self", mobile="98765 4321", village_id="1"))
    assert "mobile" in errors


def test_every_way_of_writing_a_mobile_number_is_the_same_number():
    from app.api.masters_config import national_mobile
    for typed in ("+918756564532", "08756564532", "+91 8756564532", "+91 87565 64532", "0091 8756564532", "8756564532", "87565 64532", "91 87565 64532"):
        assert national_mobile(typed) == "8756564532", typed
    assert national_mobile("87565 6453") == "875656453"  # too short stays too short, so validation refuses it
    clean, errors = check("Farmers", dict(farmer_name="X Y Z", head_of_family="Self", mobile="+91 87565 64532", village_id="1"))
    assert not errors and clean["mobile"] == "8756564532"


def test_email_is_stored_as_one_address_from_its_two_sections():
    from app.api.masters_config import compose_email
    assert compose_email("DFGH", "@Gmail.com") == "dfgh@gmail.com"
    assert compose_email("dfgh", "yahoo.com") == "dfgh@yahoo.com"
    assert compose_email("dfgh@gmail.com", "") == "dfgh@gmail.com"      # a whole address pasted into the first section
    assert compose_email("", "") == ""
    clean, errors = check("Farmers", {"farmer_name": "X Y Z", "head_of_family": "Self", "mobile": "9999999999", "village_id": "1", "email__local": "dfgh", "email__domain": "@gmail.com"})
    assert not errors and clean["email"] == "dfgh@gmail.com"
    _, errors = check("Farmers", {"farmer_name": "X Y Z", "head_of_family": "Self", "mobile": "9999999999", "village_id": "1", "email__local": "dfgh", "email__domain": ""})
    assert "email" in errors


def test_bank_account_number_is_not_treated_as_a_mobile_number():
    # only mobile / UPI fields lose a leading 0 or 91; an account number keeps every digit
    clean, errors = check("Farmers", dict(farmer_name="X Y Z", head_of_family="Self", mobile="9999999999", village_id="1", bank_account_number="0123456789012"))
    assert not errors and clean["bank_account_number"] == "0123456789012"
    clean, errors = check("Farmers", dict(farmer_name="X Y Z", head_of_family="Self", mobile="9999999999", village_id="1", bank_account_number="911234567890"))
    assert not errors and clean["bank_account_number"] == "911234567890"


def test_full_name_in_four_parts_is_stored_as_one_name():
    raw = {"farmer_name__1": "Patel", "farmer_name__2": " Ramesh ", "farmer_name__3": "Bhimjibhai", "farmer_name__4": "Devjibhai",
           "farmer_name_gu__1": "પટેલ", "farmer_name_gu__2": "રમેશ", "farmer_name_gu__3": "ભીમજીભાઈ", "farmer_name_gu__4": "",
           "mobile": "9999999999", "village_id": "1", "head_of_family__self": "1"}
    clean, errors = check("Farmers", raw)
    assert not errors and clean["farmer_name"] == "Patel Ramesh Bhimjibhai Devjibhai" and clean["farmer_name_gu"] == "પટેલ રમેશ ભીમજીભાઈ"
    clean, errors = check("Farmers", {**raw, "farmer_name__1": "", "farmer_name__2": "", "farmer_name__3": "", "farmer_name__4": ""})
    assert "farmer_name" in errors   # the name itself is required


def test_name_first_three_parts_are_mandatory_grandfather_optional():
    ok = {"farmer_name__1": "Patel", "farmer_name__2": "Ramesh", "farmer_name__3": "Bhimjibhai", "farmer_name__4": "", "head_of_family__self": "1",
          "mobile": "9999999999", "village_id": "1"}
    clean, errors = check("Farmers", ok)
    assert not errors and clean["farmer_name"] == "Patel Ramesh Bhimjibhai"
    for missing in ("farmer_name__1", "farmer_name__2", "farmer_name__3"):
        _, errors = check("Farmers", {**ok, missing: ""})
        assert "farmer_name" in errors, missing
    _, errors = check("Farmers", {**ok, "farmer_name_gu__1": "પટેલ", "farmer_name_gu__2": "રમેશ"})   # a Gujarati name, once started, needs its three parts too
    assert "farmer_name_gu" in errors


def test_head_of_family_is_self_or_name_and_father_with_the_farmers_surname():
    base = {"farmer_name__1": "Patel", "farmer_name__2": "Ramesh", "farmer_name__3": "Bhimjibhai", "mobile": "9999999999", "village_id": "1"}
    clean, errors = check("Farmers", {**base, "head_of_family__self": "1"})
    assert not errors and clean["head_of_family"] == "Self"
    clean, errors = check("Farmers", {**base, "head_of_family__name": "Bharat", "head_of_family__father": "Devjibhai"})
    assert not errors and clean["head_of_family"] == "Patel Bharat Devjibhai"
    _, errors = check("Farmers", {**base, "head_of_family__name": "Bharat", "head_of_family__father": ""})
    assert "head_of_family" in errors      # name without father's name
    _, errors = check("Farmers", base)
    assert "head_of_family" in errors      # something must be given: no payment without asking the head


def test_bank_account_number_typed_in_groups_is_stored_as_plain_digits():
    base = dict(farmer_name="X Y Z", head_of_family="Self", mobile="9999999999", village_id="1")
    clean, errors = check("Farmers", {**base, "bank_account_number": "12345 67890 12345 678"})
    assert not errors and clean["bank_account_number"] == "1234567890123456 78".replace(" ", "")
    clean, errors = check("Farmers", {**base, "bank_account_number": "0123 45678 9012"})
    assert not errors and clean["bank_account_number"] == "012345678 9012".replace(" ", "")   # leading zeros kept
    from app.core.templating import format_account
    assert format_account("123456789012345678") == "12345 67890 12345 678" and format_account("1234") == "1234" and format_account(None) == ""
