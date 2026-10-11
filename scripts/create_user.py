"""Usage: python -m scripts.create_user <username> <owner|accountant>  (prompts for password)"""
import asyncio
import getpass
import sys

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import User


async def main(username: str, role: str) -> None:
    password = getpass.getpass("Password: ")
    async with SessionLocal() as db:
        db.add(User(username=username, role=role, password_hash=hash_password(password)))
        await db.commit()


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[2] not in ("owner", "accountant"):
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
