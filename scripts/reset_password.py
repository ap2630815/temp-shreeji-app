"""Usage: python -m scripts.reset_password <username>   (prompts for the new password)"""
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import User


async def main(username: str) -> None:
    password = getpass.getpass("New password: ")
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == username))
        if user is None:
            sys.exit(f"No such user: {username}")
        user.password_hash = hash_password(password)
        await db.commit()
    print("Password updated.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1]))
