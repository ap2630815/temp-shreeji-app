"""Declarative description of every master screen: fields, labels, validation, list columns.

One generic router (app/api/masters.py) renders list/add/edit pages from these specs."""

import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, ValidationError, create_model

from app import models

MOBILE = r"^[0-9]{10}$"
IFSC = r"^[A-Z]{4}0[A-Z0-9]{6}$"
TRUCK_NO = r"^[A-Z]{2} [0-9]{2} (?: [A-Z]|[A-Z]{2}) [0-9]{4}$"
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
NAME3 = r"^\S+( \S+){2,}$"            # surname, name, father (grandfather optional): at least three words
HEAD = r"^(Self|\S+( \S+){2,})$"      # 'Self', or surname (the farmer's own) + name + father's name
BANK_ACCOUNT = r"^[0-9]{9,18}$"

REQUIRED_MSG = ("Required", "જરૂરી")
INVALID_MSG = ("Invalid", "અમાન્ય")
TOO_LONG_MSG = ("Too long", "ખૂબ લાંબું")
DUPLICATE_MSG = ("Already exists", "પહેલેથી અસ્તિત્વમાં છે")


@dataclass(frozen=True)
class F:
    """One form field. `name` is the model attribute."""

    name: str
    en: str
    gu: str
    kind: str = "text"  # text | tel | email | textarea | int | choice | date | select | fk (select of a master row, int id)
    required: bool = False
    pattern: str | None = None
    hint: tuple[str, str] | None = None
    max_length: int = 200
    normalize: str | None = None  # upper | truck_no
    choices: tuple[int, ...] = ()
    options: tuple[tuple[str, str], ...] = ()  # (value, label) pairs for kind="select"
    owner_only: bool = False
    help: tuple[str, str] | None = None
    locked: bool = False  # shown but not editable; the handler keeps the stored value
    fk: str | None = None  # for kind="fk": key into app.api.masters.FK_SOURCES
    @property
    def is_account(self) -> bool:
        """A bank account number: digits only in the column, shown in groups of five (12345 67890 12345 678)."""
        return self.kind == "tel" and self.pattern == BANK_ACCOUNT

    @property
    def is_mobile(self) -> bool:
        """A mobile / UPI number field (10 digits, shown as 98765 43210 with a country-code box). Other numeric text, like a bank account, is not."""
        return self.kind == "tel" and self.pattern == MOBILE


@dataclass(frozen=True)
class Spec:
    slug: str
    model: type
    label: tuple[str, str]
    fields: tuple[F, ...]
    list_columns: tuple[str, ...]
    search_columns: tuple[str, ...]
    order_by: str = "name"

    def field(self, name: str) -> F:
        """The field behind a list column; a dotted column ('village.village_name') shows the label of its fk field."""
        if "." in name:
            name = name.split(".")[0] + "_id"
        return next(f for f in self.fields if f.name == name)


def _mobile(name, en, gu, required=True):
    return F(name, en, gu, kind="tel", required=required, pattern=MOBILE, hint=("10 digits", "૧૦ અંક"), max_length=10)


def _upi():
    return _mobile("upi_number", "UPI number (if different from mobile)", "UPI નંબર (મોબાઇલથી અલગ હોય તો)", required=False)


def _name4_pair(en, gu, name, max_length=120):
    """A full name in four parts (surname, name, father, grandfather), stored joined by single spaces in one column; plus its Gujarati twin."""
    hint = ("Surname, name and father's name are needed", "અટક, નામ અને પિતાનું નામ જરૂરી છે")
    return [F(name, en, gu, kind="name4", required=True, pattern=NAME3, hint=hint, max_length=max_length),
            F(f"{name}_gu", f"{en} (Gujarati)", f"{gu} (ગુજરાતી)", kind="name4", pattern=NAME3, hint=hint, max_length=max_length)]


def _name_pair(en="Name", gu="નામ", name="name", required=True, max_length=200):
    return [F(name, en, gu, required=required, max_length=max_length), F(f"{name}_gu", f"{en} (Gujarati)", f"{gu} (ગુજરાતી)", max_length=max_length)]


SPECS: dict[str, Spec] = {}


def _add(spec: Spec):
    SPECS[spec.slug] = spec


def _fk(name, en, gu, source, required=True):
    return F(name, en, gu, kind="fk", fk=source, required=required)


# ---- file1-master1.txt
_add(Spec(
    slug="Villages", model=models.Village, label=("Village", "ગામ"),
    fields=(
        F("village_name", "Village name", "ગામનું નામ", required=True, max_length=30),
        F("village_name_gu", "Village name (Gujarati)", "ગામનું નામ (ગુજરાતી)", max_length=30),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ),
    list_columns=("village_name", "village_name_gu"),
    search_columns=("village_name", "village_name_gu"),
    order_by="village_name",
))

_add(Spec(
    slug="Grains", model=models.Grain, label=("Grain", "અનાજ"),
    fields=(
        F("grain_name", "Grain name", "અનાજનું નામ", required=True, max_length=30),
        F("grain_name_gu", "Grain name (Gujarati)", "અનાજનું નામ (ગુજરાતી)", max_length=30),
        F("net_bag_weight", "Net bag weight (kg)", "બેગનું ચોખ્ખું વજન (કિલો)", kind="choice", required=True, choices=(35, 50, 70, 100)),
        F("booking_weight", "Booking weight (kg)", "બુકિંગ વજન (કિલો)", kind="choice", required=True, choices=(20, 100),
          help=("The rate to industries is per this weight", "ઉદ્યોગને ભાવ આ વજન દીઠ")),
        F("grain_terms", "Default terms & conditions (clean, moisture, variety…)", "ડિફોલ્ટ શરતો (સાફ, ભેજ, જાત…)", kind="textarea"),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ),
    list_columns=("grain_name", "grain_name_gu", "net_bag_weight", "booking_weight"),
    search_columns=("grain_name", "grain_name_gu"),
    order_by="grain_name",
))

_add(Spec(
    slug="LabourGroups", model=models.LabourGroup, label=("Labour Group", "મજૂર જૂથ"),
    fields=(
        F("group_name", "Group name", "જૂથનું નામ", required=True, max_length=30),
        F("group_name_gu", "Group name (Gujarati)", "જૂથનું નામ (ગુજરાતી)", max_length=30),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ),
    list_columns=("group_name", "group_name_gu"),
    search_columns=("group_name", "group_name_gu"),
    order_by="group_name",
))

_add(Spec(
    slug="BagSuppliers", model=models.BagSupplier, label=("Bag Supplier", "બારદાન સપ્લાયર"),
    fields=(
        *_name_pair("Full name (surname, name, father)", "પૂરું નામ (અટક, નામ, પિતા)", max_length=120),
        F("pet_name", "Pet name", "ટૂંકું નામ", required=True, max_length=30),
        _mobile("mobile", "Mobile", "મોબાઇલ"),
        _upi(),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ),
    list_columns=("name", "pet_name", "mobile"),
    search_columns=("name", "name_gu", "pet_name", "mobile"),
))

_add(Spec(
    slug="Transporters", model=models.Transporter, label=("Transport", "ટ્રાન્સપોર્ટ"),
    fields=(
        F("transporter_name", "Transport name", "ટ્રાન્સપોર્ટનું નામ", required=True, max_length=120),
        F("pet_name", "Pet name", "ટૂંકું નામ", required=True, max_length=30),
        F("location", "Location", "સ્થળ", required=True, max_length=60),
        F("owner_name", "Owner name (surname, name, father)", "માલિકનું નામ (અટક, નામ, પિતા)", required=True, max_length=120),
        F("owner_name_gu", "Owner name (Gujarati)", "માલિકનું નામ (ગુજરાતી)", max_length=120),
        _mobile("mobile", "Mobile", "મોબાઇલ"),
        _upi(),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ),
    list_columns=("transporter_name", "pet_name", "location", "mobile"),
    search_columns=("transporter_name", "pet_name", "location", "owner_name", "mobile"),
    order_by="transporter_name",
))

_add(Spec(
    slug="Trucks", model=models.Truck, label=("Truck", "ટ્રક"),
    fields=(
        F("truck_number", "Truck number", "ટ્રક નંબર", required=True, pattern=TRUCK_NO,
          hint=("e.g. GJ 03 AB 1234 or GJ 14  X 6720 (spaces are added as you type)", "દા.ત. GJ 03 AB 1234 અથવા GJ 14  X 6720 (ટાઇપ કરતાં જગ્યા આપોઆપ ઉમેરાશે)"), max_length=13, normalize="truck_no"),
        F("truck_owner_name", "Owner name (surname, name, father)", "માલિકનું નામ (અટક, નામ, પિતા)", required=True, max_length=120),
        _mobile("truck_owner_mobile", "Owner mobile (payments go to the owner)", "માલિકનો મોબાઇલ (ચુકવણી માલિકને)"),
        F("driver_name", "Driver name (surname, name, father)", "ડ્રાઇવરનું નામ (અટક, નામ, પિતા)", required=True, max_length=120),
        _mobile("driver_mobile", "Driver mobile", "ડ્રાઇવરનો મોબાઇલ"),
        _upi(),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ),
    list_columns=("truck_number", "truck_owner_name", "driver_name", "driver_mobile"),
    search_columns=("truck_number", "truck_owner_name", "driver_name", "driver_mobile", "truck_owner_mobile"),
    order_by="truck_number",
))

_add(Spec(
    slug="Industries", model=models.Industry, label=("Industry", "ઉદ્યોગ"),
    fields=(
        *_name_pair("Industry name", "ઉદ્યોગનું નામ", name="industrialist_name", max_length=120),
        F("owner_name", "Owner name", "માલિકનું નામ", required=True, max_length=120),
        _mobile("owner_mobile", "Owner mobile", "માલિકનો મોબાઇલ"),
        F("supervisor_name", "Supervisor name", "સુપરવાઇઝરનું નામ", required=True, max_length=120),
        _mobile("supervisor_mobile", "Supervisor mobile", "સુપરવાઇઝરનો મોબાઇલ"),
        F("grain", "Grain", "અનાજ", required=True, max_length=60),
        F("location", "Location", "સ્થળ", required=True, max_length=120),
        F("quality_expectation", "Quality expectation", "ગુણવત્તાની અપેક્ષા", kind="textarea"),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ),
    list_columns=("industrialist_name", "grain", "location", "supervisor_mobile"),
    search_columns=("industrialist_name", "industrialist_name_gu", "owner_name", "supervisor_name", "grain", "location"),
    order_by="industrialist_name",
))

_add(Spec(
    slug="Brokers", model=models.Broker, label=("Broker", "દલાલ"),
    fields=(
        *_name_pair("Broker name", "દલાલનું નામ", name="broker_name", max_length=120),
        _mobile("mobile", "Mobile", "મોબાઇલ"),
        _upi(),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ),
    list_columns=("broker_name", "mobile"),
    search_columns=("broker_name", "broker_name_gu", "mobile"),
    order_by="broker_name",
))

# ---- file2-master2.txt
_add(Spec(
    slug="Farmers", model=models.Farmer, label=("Farmer", "ખેડૂત"),
    fields=(
        *_name4_pair("Full name (surname, name, father, grandfather)", "પૂરું નામ (અટક, નામ, પિતા, દાદા)", name="farmer_name", max_length=120),
        F("head_of_family", "Head of family (ask him before any payment)", "કુટુંબના વડા (ચુકવણી પહેલાં તેમને પૂછો)", kind="head", required=True, pattern=HEAD, max_length=100,
          hint=("Tick Self, or enter the head's name and father's name", "સ્વયં પસંદ કરો, અથવા વડાનું નામ અને પિતાનું નામ લખો")),
        _mobile("mobile", "Mobile", "મોબાઇલ"),
        F("email", "Email", "ઈમેલ", kind="email", pattern=EMAIL, hint=("name@example.com", "name@example.com"), max_length=60),
        _fk("village_id", "Village", "ગામ", "village"),
        F("house", "House / address", "ઘર / સરનામું", kind="textarea"),
        _upi(),
        F("bank_account_number", "Bank account number", "બેંક ખાતા નંબર", kind="tel", pattern=BANK_ACCOUNT,
          hint=("9–18 digits", "૯–૧૮ અંક"), max_length=18),
        F("bank_name", "Bank name", "બેંકનું નામ", max_length=30),
        F("bank_branch", "Branch name", "શાખાનું નામ", max_length=30),
        F("ifsc_code", "IFSC code", "IFSC કોડ", pattern=IFSC, hint=("e.g. SBIN0001234", "દા.ત. SBIN0001234"),
          max_length=11, normalize="upper"),
        F("public_figure", "Public figure / influence", "જાહેર વ્યક્તિ / પ્રભાવ", kind="textarea"),
        F("description", "Private note (owner only)", "ખાનગી નોંધ (ફક્ત માલિક)", kind="textarea", owner_only=True),
    ),
    list_columns=("farmer_name", "village.village_name", "mobile", "head_of_family"),
    search_columns=("farmer_name", "farmer_name_gu", "mobile"),
    order_by="farmer_name",
))

_add(Spec(
    slug="Labours", model=models.Labour, label=("Labour", "મજૂર"),
    fields=(
        *_name_pair("Labour name", "મજૂરનું નામ", name="labour_name", max_length=120),
        _fk("labour_group_id", "Labour group", "મજૂર જૂથ", "labour_group"),
        _mobile("mobile", "Mobile", "મોબાઇલ"),
        _upi(),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ),
    list_columns=("labour_name", "labour_group.group_name", "mobile"),
    search_columns=("labour_name", "labour_name_gu", "mobile"),
    order_by="labour_name",
))

_add(Spec(
    slug="LabourWages", model=models.LabourGroupWage, label=("Labour Wages", "મજૂરી દર"),
    fields=(
        _fk("labour_group_id", "Labour group", "મજૂર જૂથ", "labour_group"),
        _fk("grain_id", "Grain", "અનાજ", "grain"),
        F("weighing_rate", "Weighing rate (₹ per bag)", "તોલાઈ દર (₹ બેગ દીઠ)", kind="int", required=True),
        F("loading_rate", "Loading rate (₹ per bag)", "લોડિંગ દર (₹ બેગ દીઠ)", kind="int", required=True),
        F("pulling_rate", "Pulling rate (₹ per bag)", "ખેંચાઈ દર (₹ બેગ દીઠ)", kind="int", required=True),
        F("mixing_rate", "Mixing rate (₹ per bag)", "મિક્સિંગ દર (₹ બેગ દીઠ)", kind="int", required=True),
        F("other_expenses", "Other expenses (₹)", "અન્ય ખર્ચ (₹)", kind="int"),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ),
    list_columns=("labour_group.group_name", "grain.grain_name", "weighing_rate", "loading_rate", "pulling_rate", "mixing_rate"),
    search_columns=("description",),
    order_by="id",
))

_add(Spec(
    slug="Brokerages", model=models.Brokerage, label=("Brokerage", "દલાલી"),
    fields=(
        _fk("broker_id", "Broker", "દલાલ", "broker"),
        _fk("grain_id", "Grain", "અનાજ", "grain"),
        F("brokerage_per_bag", "Brokerage per bag (₹)", "બેગ દીઠ દલાલી (₹)", kind="int", required=True),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ),
    list_columns=("broker.broker_name", "grain.grain_name", "brokerage_per_bag"),
    search_columns=("description",),
    order_by="id",
))


def compose_email(local: str | None, domain: str | None) -> str:
    """The two sections of the email field -> the stored address, lower-case: ('dfgh', '@gmail.com') -> 'dfgh@gmail.com'. A full address pasted into the
    first section is split at its '@'; nothing typed in either section means no email."""
    local, domain = (local or "").strip(), (domain or "").strip().lstrip("@").strip()
    if "@" in local:
        local, pasted = local.split("@", 1)
        domain = domain or pasted.strip().lstrip("@")
    return f"{local}@{domain}".lower() if (local or domain) else ""


def national_mobile(value: str) -> str:
    """+918756564532, 08756564532, +91 87565 64532, 0091 8756564532 and 8756564532 all mean 8756564532: strip the country code / trunk 0,
    keep the 10 digits. Anything that does not look like one of those is returned as plain digits (for validation to refuse)."""
    digits = re.sub(r"\D", "", value)
    for prefix, length in (("0091", 14), ("91", 12), ("0", 11)):
        if len(digits) == length and digits.startswith(prefix):
            return digits[len(prefix):]
    return digits or value


def format_truck_no(value: str) -> str:
    """'gj03ab1234' / 'GJ-03 AB-1234' -> 'GJ 03 AB 1234'; 'gj14x6720' -> 'GJ 14  X 6720' (a one-letter series is padded to two columns,
    so the numbers line up). Anything that does not fit stays as typed, upper-cased, for validation."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    m = re.fullmatch(r"([A-Z]{2})([0-9]{2})([A-Z]{1,2})([0-9]{4})", cleaned)
    return f"{m[1]} {m[2]} {m[3].rjust(2)} {m[4]}" if m else value.strip().upper()


def normalize(spec: Spec, raw: dict[str, str], include_owner_only: bool) -> dict[str, Any]:
    """Strip, blank -> None, apply per-field normalisation, parse ints. Skips fields the caller may not edit."""
    out: dict[str, Any] = {}
    for f in spec.fields:
        if f.owner_only and not include_owner_only:
            continue
        value = (raw.get(f.name) or "").strip()
        if f.kind == "name4" and any(f"{f.name}__{i}" in raw for i in range(1, 5)):
            value = " ".join(" ".join((raw.get(f"{f.name}__{i}") or "").split()) for i in range(1, 5)).strip()
            value = " ".join(value.split())  # parts left empty leave no gaps
        if f.kind == "head" and any(f"{f.name}__{k}" in raw for k in ("self", "name", "father")):
            # 'Self' (the farmer himself), or the farmer's own surname + the head's name + his father's name, joined by spaces
            if raw.get(f"{f.name}__self"):
                value = "Self"
            else:
                surname = (out.get("farmer_name") or "").split(" ")[0]
                value = " ".join(" ".join(p.split()) for p in (surname, raw.get(f"{f.name}__name") or "", raw.get(f"{f.name}__father") or "") if p.strip())
        if f.kind == "email" and (f"{f.name}__local" in raw or f"{f.name}__domain" in raw):
            value = compose_email(raw.get(f"{f.name}__local"), raw.get(f"{f.name}__domain"))
        if f.is_account:
            value = re.sub(r"\s", "", value)  # '12345 67890 12345' -> '123456789012345'
        if f.is_mobile:
            value = national_mobile(value)  # '+91 98765 43210' / '098765 43210' / '98765 43210' -> '9876543210'
        if f.normalize == "truck_no":
            value = format_truck_no(value)
        elif f.normalize == "upper":
            value = value.upper()
        if value == "":
            out[f.name] = None
            continue
        if f.kind in ("int", "choice", "fk"):
            try:
                value = int(value)
            except ValueError:
                pass  # left as a string so validation reports it
        out[f.name] = value
    return out


_models: dict[str, type[BaseModel]] = {}


def _validator(spec: Spec) -> type[BaseModel]:
    if spec.slug not in _models:
        definitions: dict[str, Any] = {}
        for f in spec.fields:
            if f.kind == "int":
                ann: Any = Annotated[int, Field(ge=0, le=10_000_000)]
            elif f.kind == "fk":
                ann = Annotated[int, Field(gt=0)]
            elif f.kind == "choice":
                ann = Literal[f.choices]  # type: ignore[valid-type]
            else:
                ann = Annotated[str, Field(min_length=1, max_length=f.max_length, pattern=f.pattern)]
            definitions[f.name] = (ann, ...) if f.required else (ann | None, None)
        _models[spec.slug] = create_model(f"{spec.model.__name__}Form", **definitions)
    return _models[spec.slug]


def validate(spec: Spec, data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, tuple[str, str]]]:
    """Returns (clean values, {field: (en, gu) error})."""
    return run_validation(_validator(spec), spec.fields, data)


def run_validation(
    model: type[BaseModel], fields: tuple[F, ...] | list[F], data: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, tuple[str, str]]]:
    by_name = {f.name: f for f in fields}
    try:
        return model(**data).model_dump(), {}
    except ValidationError as exc:
        errors: dict[str, tuple[str, str]] = {}
        for err in exc.errors():
            name = str(err["loc"][0])
            f = by_name[name]
            if err["type"] in ("missing", "string_too_short", "none_required"):
                errors[name] = REQUIRED_MSG
            elif err["type"] == "string_too_long":
                errors[name] = TOO_LONG_MSG
            elif f.hint:
                errors[name] = (f"{INVALID_MSG[0]}: {f.hint[0]}", f"{INVALID_MSG[1]}: {f.hint[1]}")
            elif f.kind == "choice":
                errors[name] = (f"Choose one of {', '.join(map(str, f.choices))}", "આમાંથી એક પસંદ કરો")
            else:
                errors[name] = INVALID_MSG
        return {}, errors
