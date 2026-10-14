from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi_csrf_protect import CsrfProtect
from fastapi_csrf_protect.exceptions import CsrfProtectError

from app.api import account, auth, bookings, costs, masters, payments, purchases, receivables, reports, trips, years
from app.api.masters_config import SPECS
from app.api.deps import current_user
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.templating import BASE_DIR, render_with_csrf
from sqlalchemy import select

from app.models import Grain, User


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
    """Grain names for the toolbar dropdown (page loads only)."""
    request.state.grains = []
    if request.method == "GET" and not request.url.path.startswith("/static") and "hx-request" not in request.headers:
        try:
            async with SessionLocal() as db:
                request.state.grains = (await db.execute(select(Grain.id, Grain.grain_name.label("name"), Grain.grain_name_gu.label("name_gu")).order_by(Grain.grain_name))).all()
        except Exception:
            request.state.grains = []
    return await call_next(request)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(auth.router)
app.include_router(account.router)
app.include_router(masters.router)
app.include_router(purchases.router)
app.include_router(bookings.router)
app.include_router(costs.router)
app.include_router(reports.router)
app.include_router(trips.router)
app.include_router(payments.router)
app.include_router(receivables.router)
app.include_router(years.router)


@app.exception_handler(CsrfProtectError)
async def csrf_error_handler(request: Request, exc: CsrfProtectError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends()):
    return render_with_csrf(request, csrf, "dashboard.html", user=user, masters=SPECS)
