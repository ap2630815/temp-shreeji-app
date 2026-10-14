from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from itsdangerous import BadData, URLSafeTimedSerializer

from app.core.config import settings
from app.core.labels import LABELS

BASE_DIR = Path(__file__).resolve().parent.parent

templates = Jinja2Templates(directory=BASE_DIR / "templates")
from app.api.masters_config import SPECS

templates.env.globals["L"] = LABELS


def cell(row, path: str):
    """Value of a (possibly dotted) attribute path: cell(farmer, 'village.village_name')."""
    for part in path.split("."):
        row = getattr(row, part)
    return "" if row is None else row


templates.env.globals["cell"] = cell


def year_span(label: str | None = None) -> tuple[str, str]:
    """('2026-Oct', '2027-Sept') for a '2026-27' label; defaults to the current Oct-Sep business year."""
    from datetime import date

    if label:
        start = int(label[:4])
    else:
        d = date.today()
        start = d.year if d.month >= 10 else d.year - 1
    return f"{start}-Oct", f"{start + 1}-Sept"


def default_year_label() -> str:
    start = int(year_span()[0][:4])
    return f"{start}-{(start + 1) % 100:02d}"


def year_choices(count: int = 5) -> list[str]:
    start = int(year_span()[0][:4])
    return [f"{y}-{(y + 1) % 100:02d}" for y in range(start, start - count, -1)]


templates.env.globals["year_span"] = year_span
templates.env.globals["default_year_label"] = default_year_label
templates.env.globals["year_choices"] = year_choices
templates.env.globals["MASTERS"] = SPECS  # {{ L['farmer'][0]}} {{ L['farmer'][1] }}


def inr(value) -> str:
    """Whole rupees with Indian digit grouping: 1234567 -> ₹12,34,567."""
    n = int(value)
    sign = "-" if n < 0 else ""
    digits = str(abs(n))
    head, tail = digits[:-3], digits[-3:]
    if head:
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        tail = ",".join(groups) + "," + tail
    return f"{sign}₹{tail}"


templates.env.filters["inr"] = inr


def render(request: Request, name: str, status_code: int = 200, **context):
    return templates.TemplateResponse(request, name, context, status_code=status_code)


_csrf_serializer = URLSafeTimedSerializer(settings.csrf_secret_key, salt="fastapi-csrf-token")
CSRF_REUSE_SECONDS = settings.session_max_age // 2


def _existing_csrf_token(request: Request) -> str | None:
    """The token behind a still-fresh CSRF cookie, so a second tab/page does not invalidate the first."""
    signed = request.cookies.get("fastapi-csrf-token")
    if not signed:
        return None
    try:
        return _csrf_serializer.loads(signed, max_age=CSRF_REUSE_SECONDS)
    except BadData:
        return None


def render_with_csrf(request: Request, csrf, name: str, **context):
    """Render a full page that issues htmx POSTs: embeds a CSRF token and (re)sets its cookie only when needed.

    Reusing a fresh token keeps every open tab valid; issuing a new one per page load would break all but the last."""
    token = _existing_csrf_token(request)
    if token is None:
        token, signed = csrf.generate_csrf_tokens()
        response = render(request, name, csrf_token=token, **context)
        csrf.set_csrf_cookie(signed, response)
        return response
    return render(request, name, csrf_token=token, **context)
