from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# bcrypt uses only the first 72 bytes: a longer password would also accept
# any other password that starts with the same 72 bytes. (A Tamil letter is
# 3 bytes, so this can be as few as 24 characters.)
MAX_PASSWORD_BYTES = 72


def password_too_long(plain_password: str) -> bool:
    return len(plain_password.encode("utf-8")) > MAX_PASSWORD_BYTES


def hash_password(plain_password: str) -> str:
    if not plain_password:
        raise ValueError("password must not be empty.")
    if password_too_long(plain_password):
        raise ValueError(f"password must be at most {MAX_PASSWORD_BYTES} bytes.")
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    if not plain_password or not password_hash:
        return False
    return _pwd_context.verify(plain_password, password_hash)