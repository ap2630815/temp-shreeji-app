from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi_csrf_protect import CsrfProtect
from fastapi_csrf_protect.exceptions import CsrfProtectError

from app.api import account, analysis, auth, bookings, costs, farmer_entries, masters, payments, purchase_group, receivables, reports, trips, years
from app.api.masters_config import SPECS
from app.api.deps import current_user
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.templating import BASE_DIR, render_with_csrf
from sqlalchemy import select

from app.models import Grain, User, Village


@CsrfProtect.load_config
def csrf_settings():
    return [
        ("secret_key", settings.csrf_secret_key),
        ("cookie_samesite", "lax"),
        ("cookie_secure", settings.cookie_secure),
        ("header_name", "X-CSRF-Token"),
        ("header_type", None),
        ("max_age", settings.session_max_age),
    ]


app = FastAPI(title="Shreeji Grain Trading")


@app.middleware("http")
async def load_grains(request: Request, call_next):
    """Grain and village names for the toolbar dropdowns (page loads only)."""
    request.state.grains = []
    request.state.villages = []
    if request.method == "GET" and request.url.query:
        # the toolbar's "Village" / "Grain" placeholder submits village_id= / grain_id= (empty): treat blank (or non-numeric id) filters as "not chosen"
        # instead of letting the integer parsing fail
        kept = [(k, v) for k, v in request.query_params.multi_items() if v.strip() and (k not in ("village_id", "grain_id") or v.strip().isdigit())]
        if len(kept) != len(request.query_params.multi_items()):
            request.scope["query_string"] = urlencode(kept).encode()
            request._query_params = request.query_params.__class__(kept)  # keep request.query_params in step for templates
    if request.method == "GET" and not request.url.path.startswith("/static") and "hx-request" not in request.headers:
        try:
            async with SessionLocal() as db:
                request.state.grains = (await db.execute(select(Grain.id, Grain.grain_name.label("name"), Grain.grain_name_gu.label("name_gu")).order_by(Grain.grain_name))).all()
                request.state.villages = (await db.execute(select(Village.id, Village.village_name.label("name"), Village.village_name_gu.label("name_gu")).order_by(Village.village_name))).all()
        except Exception:
            request.state.grains = []
            request.state.villages = []
    return await call_next(request)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(auth.router)
app.include_router(account.router)
app.include_router(masters.router)
app.include_router(farmer_entries.router)
app.include_router(purchase_group.router)
app.include_router(bookings.router)
app.include_router(costs.router)
app.include_router(reports.router)
app.include_router(trips.router)
app.include_router(payments.router)
app.include_router(receivables.router)
app.include_router(analysis.router)
app.include_router(years.router)


@app.exception_handler(CsrfProtectError)
async def csrf_error_handler(request: Request, exc: CsrfProtectError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.get("/Purchases")
async def old_purchases_url():
    return RedirectResponse("/PurchaseFarmersEntries", status_code=307)


@app.get("/Purchases/{rest:path}")
async def old_purchase_urls(rest: str):
    return RedirectResponse(f"/PurchaseGroup/{rest}", status_code=307)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends()):
    return render_with_csrf(request, csrf, "dashboard.html", user=user, masters=SPECS)
