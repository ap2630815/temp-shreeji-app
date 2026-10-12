"""Usage: python -m scripts.create_user <username> <owner|accountant>  (prompts for password)"""
import asyncio
import getpass
import sys

from sqlalchemy.exc import DBAPIError

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import User


async def main(username: str, role: str) -> None:
    password = getpass.getpass("Password: ")
    async with SessionLocal() as db:
        db.add(User(username=username, role=role, password_hash=hash_password(password)))
        try:
            await db.commit()
        except DBAPIError as exc:  # IntegrityError is a subclass
            sys.exit(f"Cannot create user (limit: 1 owner, 2 accountants; unique username): {exc.orig}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[2] not in ("owner", "accountant"):
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
