from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import SESSION_COOKIE, read_session_token
from app.models import User


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    user_id = read_session_token(token) if token else None
    user = await db.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        # full page loads go to login; HTMX requests get a client-side redirect
        headers = {"HX-Redirect": "/Login"} if request.headers.get("HX-Request") else {"Location": "/Login"}
        raise HTTPException(status_code=401 if "HX-Redirect" in headers else 303, headers=headers)
    return user


def require_role(*roles: str):
    async def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user

    return checker
