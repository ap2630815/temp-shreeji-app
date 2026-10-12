from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi_csrf_protect import CsrfProtect
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.db import get_db
from app.core.security import hash_password, verify_password
from app.core.templating import render, render_with_csrf
from app.models import User

router = APIRouter(prefix="/account")

MIN_PASSWORD_LENGTH = 8


@router.get("/password", response_class=HTMLResponse)
async def password_page(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends()):
    return render_with_csrf(request, csrf, "account_password.html", user=user)


@router.post("/password", response_class=HTMLResponse)
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user: User = Depends(current_user),
    csrf: CsrfProtect = Depends(),
    db: AsyncSession = Depends(get_db),
):
    await csrf.validate_csrf(request)
    error = None
    if not verify_password(user.password_hash, current_password):
        error = "pw_wrong_current"
    elif len(new_password) < MIN_PASSWORD_LENGTH:
        error = "pw_too_short"
    elif new_password != confirm_password:
        error = "pw_mismatch"
    elif new_password == current_password:
        error = "pw_same"
    # htmx does not swap 4xx, so feedback is returned with 200
    if error:
        return render(request, "partials/flash.html", kind="error", key=error)
    user.password_hash = hash_password(new_password)
    await db.commit()
    return render(request, "partials/flash.html", kind="success", key="pw_changed")
