"""Declarative description of every master screen: fields, labels, validation, list columns.

One generic router (app/api/masters.py) renders list/add/edit pages from these specs."""

import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, ValidationError, create_model

from app import models

MOBILE = r"^[0-9]{10}$"
IFSC = r"^[A-Z]{4}0[A-Z0-9]{6}$"
TRUCK_NO = r"^[A-Z]{2}[0-9]{2}[A-Z]{1,2}[0-9]{4}$"
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
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
    kind: str = "text"  # text | tel | email | textarea | int | choice | date | select
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
        return next(f for f in self.fields if f.name == name)


def _mobile(name, en, gu, required=True):
    return F(name, en, gu, kind="tel", required=required, pattern=MOBILE, hint=("10 digits", "૧૦ અંક"), max_length=10)


def _upi():
    return _mobile("upi_number", "UPI number (if different from mobile)", "UPI નંબર (મોબાઇલથી અલગ હોય તો)", required=False)


def _name_pair(en="Name", gu="નામ", name="name", required=True, max_length=200):
    return [F(name, en, gu, required=required, max_length=max_length), F(f"{name}_gu", f"{en} (Gujarati)", f"{gu} (ગુજરાતી)", max_length=max_length)]


SPECS: dict[str, Spec] = {}


def _add(spec: Spec):
    SPECS[spec.slug] = spec


_add(Spec(
    slug="farmers", model=models.Farmer, label=("Farmer", "ખેડૂત"),
    fields=(
        *_name_pair("Full name (surname, name, father, grandfather)", "પૂરું નામ (અટક, નામ, પિતા, દાદા)", max_length=120),
        F("head_of_family", "Head of family (verify before payment)", "કુટુંબના વડા (ચુકવણી પહેલાં ચકાસો)", max_length=60),
        _mobile("mobile", "Mobile", "મોબાઇલ"),
        F("email", "Email", "ઈમેલ", kind="email", pattern=EMAIL, hint=("name@example.com", "name@example.com"), max_length=60),
        F("village", "Village", "ગામ", required=True, max_length=30),
        F("village_gu", "Village (Gujarati)", "ગામ (ગુજરાતી)", max_length=30),
        F("house", "House / address", "ઘર / સરનામું", kind="textarea"),
        _upi(),
        F("bank_account_number", "Bank account number", "બેંક ખાતા નંબર", kind="tel", pattern=BANK_ACCOUNT,
          hint=("9–18 digits", "૯–૧૮ અંક"), max_length=18),
        F("bank_name", "Bank name", "બેંકનું નામ", max_length=30),
        F("bank_branch", "Branch name", "શાખાનું નામ", max_length=30),
        F("ifsc_code", "IFSC code", "IFSC કોડ", pattern=IFSC, hint=("e.g. SBIN0001234", "દા.ત. SBIN0001234"),
          max_length=11, normalize="upper"),
        F("description", "Private note (owner only)", "ખાનગી નોંધ (ફક્ત માલિક)", kind="textarea", owner_only=True),
        F("public_figure", "Public figure / influence", "જાહેર વ્યક્તિ / પ્રભાવ", kind="textarea"),
    ),
    list_columns=("name", "village", "mobile"),
    search_columns=("name", "name_gu", "village", "village_gu", "mobile"),
))

_add(Spec(
    slug="bag-suppliers", model=models.BagSupplier, label=("Bag Supplier", "બારદાન સપ્લાયર"),
    fields=(
        *_name_pair("Full name (surname, name, father)", "પૂરું નામ (અટક, નામ, પિતા)", max_length=120),
        F("pet_name", "Pet name", "ટૂંકું નામ", required=True, max_length=30),
        _mobile("mobile", "Mobile", "મોબાઇલ"),
        F("email", "Email", "ઈમેલ", kind="email", pattern=EMAIL, hint=("name@example.com", "name@example.com"), max_length=60),
        _upi(),
    ),
    list_columns=("name", "pet_name", "mobile"),
    search_columns=("name", "name_gu", "pet_name", "mobile"),
))

_add(Spec(
    slug="labour", model=models.LabourGroup, label=("Labour Group", "મજૂર જૂથ"),
    fields=(
        *_name_pair("Leader name (surname, name, father)", "મુકાદમનું નામ (અટક, નામ, પિતા)", max_length=120),
        _mobile("mobile", "Mobile", "મોબાઇલ"),
        F("group_name", "Group name", "જૂથનું નામ", required=True, max_length=30),
        F("group_name_gu", "Group name (Gujarati)", "જૂથનું નામ (ગુજરાતી)", max_length=30),
    ),
    list_columns=("group_name", "name", "mobile"),
    search_columns=("name", "name_gu", "group_name", "group_name_gu", "mobile"),
    order_by="group_name",
))

_add(Spec(
    slug="transporters", model=models.Transporter, label=("Transport", "ટ્રાન્સપોર્ટ"),
    fields=(
        F("name", "Transport name", "ટ્રાન્સપોર્ટનું નામ", required=True, max_length=120),
        F("pet_name", "Pet name", "ટૂંકું નામ", required=True, max_length=30),
        F("location", "Location", "સ્થળ", required=True, max_length=60),
        F("owner_name", "Owner name (surname, name, father)", "માલિકનું નામ (અટક, નામ, પિતા)", required=True, max_length=120),
        F("owner_name_gu", "Owner name (Gujarati)", "માલિકનું નામ (ગુજરાતી)", max_length=120),
        _mobile("mobile", "Mobile", "મોબાઇલ"),
        _upi(),
    ),
    list_columns=("name", "pet_name", "location", "mobile"),
    search_columns=("name", "pet_name", "location", "owner_name", "mobile"),
))

_add(Spec(
    slug="trucks", model=models.Truck, label=("Truck", "ટ્રક"),
    fields=(
        F("truck_number", "Truck number", "ટ્રક નંબર", required=True, pattern=TRUCK_NO,
          hint=("e.g. GJ03AB1234", "દા.ત. GJ03AB1234"), max_length=10, normalize="truck_no"),
        F("owner_name", "Owner name (surname, name, father)", "માલિકનું નામ (અટક, નામ, પિતા)", required=True, max_length=120),
        _mobile("owner_mobile", "Owner mobile", "માલિકનો મોબાઇલ"),
        F("driver_name", "Driver name (surname, name, father)", "ડ્રાઇવરનું નામ (અટક, નામ, પિતા)", required=True, max_length=120),
        _mobile("driver_mobile", "Driver mobile", "ડ્રાઇવરનો મોબાઇલ"),
        _upi(),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ),
    list_columns=("truck_number", "driver_name", "driver_mobile"),
    search_columns=("truck_number", "owner_name", "driver_name", "driver_mobile", "owner_mobile"),
    order_by="truck_number",
))

_add(Spec(
    slug="industries", model=models.Industry, label=("Industry", "ઉદ્યોગ"),
    fields=(
        *_name_pair("Industry name", "ઉદ્યોગનું નામ", max_length=120),
        F("owner_name", "Owner name", "માલિકનું નામ", required=True, max_length=120),
        _mobile("owner_mobile", "Owner mobile", "માલિકનો મોબાઇલ"),
        F("supervisor_name", "Supervisor name", "સુપરવાઇઝરનું નામ", required=True, max_length=120),
        _mobile("supervisor_mobile", "Supervisor mobile", "સુપરવાઇઝરનો મોબાઇલ"),
        F("product", "Product", "ઉત્પાદન", required=True, max_length=60),
        F("location", "Location", "સ્થળ", required=True, max_length=120),
        F("required_quality", "Required quality", "જરૂરી ગુણવત્તા", kind="textarea"),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ),
    list_columns=("name", "product", "location", "supervisor_mobile"),
    search_columns=("name", "name_gu", "owner_name", "supervisor_name", "product", "location"),
))

_add(Spec(
    slug="brokers", model=models.Broker, label=("Broker", "દલાલ"),
    fields=(
        *_name_pair("Broker name", "દલાલનું નામ", max_length=120),
        _mobile("mobile", "Mobile", "મોબાઇલ"),
        F("brokerage_per_truck", "Brokerage per truck (₹)", "ટ્રક દીઠ દલાલી (₹)", kind="int", required=True),
        _upi(),
    ),
    list_columns=("name", "mobile", "brokerage_per_truck"),
    search_columns=("name", "name_gu", "mobile"),
))

_add(Spec(
    slug="grains", model=models.Grain, label=("Grain", "અનાજ"),
    fields=(
        *_name_pair("Grain name", "અનાજનું નામ", max_length=30),
        F("default_net_weight", "Net bag weight (kg)", "બેગનું ચોખ્ખું વજન (કિલો)", kind="choice", required=True,
          choices=(35, 50, 70, 100)),
        F("default_terms", "Default terms & conditions (clean, moisture, variety…)",
          "ડિફોલ્ટ શરતો (સાફ, ભેજ, જાત…)", kind="textarea"),
    ),
    list_columns=("name", "name_gu", "default_net_weight"),
    search_columns=("name", "name_gu"),
))


def normalize(spec: Spec, raw: dict[str, str], include_owner_only: bool) -> dict[str, Any]:
    """Strip, blank -> None, apply per-field normalisation, parse ints. Skips fields the caller may not edit."""
    out: dict[str, Any] = {}
    for f in spec.fields:
        if f.owner_only and not include_owner_only:
            continue
        value = (raw.get(f.name) or "").strip()
        if f.normalize == "truck_no":
            value = re.sub(r"[\s\-]", "", value).upper()
        elif f.normalize == "upper":
            value = value.upper()
        if value == "":
            out[f.name] = None
            continue
        if f.kind in ("int", "choice"):
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
