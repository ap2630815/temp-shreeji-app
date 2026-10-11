from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.core.config import settings

SESSION_COOKIE = "shreeji_session"

_hasher = PasswordHasher()
_signer = URLSafeTimedSerializer(settings.secret_key, salt="session")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def make_session_token(user_id: int) -> str:
    return _signer.dumps({"uid": user_id})


def read_session_token(token: str) -> int | None:
    try:
        data = _signer.loads(token, max_age=settings.session_max_age)
    except BadSignature:
        return None
    return data.get("uid")
