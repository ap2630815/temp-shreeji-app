from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from fastapi_csrf_protect import CsrfProtect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.core.config import settings
from app.core.db import get_db
from app.core.security import SESSION_COOKIE, make_session_token, verify_password
from app.core.templating import render, render_with_csrf
from app.models import User

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, csrf: CsrfProtect = Depends()):
    return render_with_csrf(request, csrf, "login.html")


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf: CsrfProtect = Depends(),
    db: AsyncSession = Depends(get_db),
):
    await csrf.validate_csrf(request)
    user = await db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active or not verify_password(user.password_hash, password):
        return render(request, "partials/login_error.html")  # 200: htmx does not swap 4xx
    response = Response(status_code=204, headers={"HX-Redirect": "/"})
    response.set_cookie(
        SESSION_COOKIE,
        make_session_token(user.id),
        max_age=settings.session_max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return response


@router.post("/logout")
async def logout(request: Request, csrf: CsrfProtect = Depends(), _: User = Depends(current_user)):
    await csrf.validate_csrf(request)
    response = Response(status_code=204, headers={"HX-Redirect": "/login"})
    response.delete_cookie(SESSION_COOKIE)
    return response
