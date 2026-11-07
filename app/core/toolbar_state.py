"""The toolbar filters (village, grain, date) are remembered for the whole login session, in one browser-session cookie.

Rule: a filter stays chosen across every page change until the user changes it (a drop-down, or "Filter on" = clear all) or logs out.
- A page load that carries filter keys is a manual change: a key with a value sets it, a key left empty ("All") removes it.
  Keys absent from the URL (e.g. a filter greyed out on that page) leave the stored value alone.
- A page load without them gets the stored filters added to its query string, so pages and the toolbar read them as usual.
- `?filters=clear` removes everything.
"""

from datetime import date
from urllib.parse import parse_qsl, urlencode

from app.core.periods import PERIOD_KEYS

COOKIE = "toolbar_filters"
KEYS = ("village_id", "grain_id", "period", "on_date")


def _clean(state: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k in ("village_id", "grain_id"):
        if state.get(k, "").isdigit():
            out[k] = state[k]
    p = state.get("period", "")
    if p in PERIOD_KEYS:
        out["period"] = p
    elif p == "date":
        try:
            date.fromisoformat(state.get("on_date", ""))
            out["period"], out["on_date"] = "date", state["on_date"]
        except ValueError:
            pass
    return out


def load(cookie: str | None) -> dict[str, str]:
    return _clean(dict(parse_qsl(cookie or "")))


def resolve(query: list[tuple[str, str]], cookie: str | None) -> tuple[list[tuple[str, str]], dict[str, str], bool]:
    """(new query items, filters to remember, changed?) for one full-page GET."""
    stored = load(cookie)
    if any(k == "filters" and v == "clear" for k, v in query):
        return [(k, v) for k, v in query if k not in KEYS and k != "filters"], {}, bool(stored)
    sent = {k: v.strip() for k, v in query if k in KEYS}
    state = dict(stored)
    if any(k in sent for k in ("village_id", "grain_id")):
        for k in ("village_id", "grain_id"):
            if k in sent:
                state.pop(k, None)
                if sent[k].isdigit():
                    state[k] = sent[k]
    if "period" in sent:
        state.pop("period", None), state.pop("on_date", None)
        if sent["period"]:
            state["period"] = sent["period"]
            if sent.get("on_date"):
                state["on_date"] = sent["on_date"]
    state = _clean(state)
    items = [(k, v) for k, v in query if v.strip() and k not in KEYS]
    items += list(state.items())  # the stored filters, which include anything just chosen
    return items, state, state != stored


def dump(state: dict[str, str]) -> str:
    return urlencode(state)
