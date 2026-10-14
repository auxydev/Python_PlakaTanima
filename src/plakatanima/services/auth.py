"""Kullanıcılar, roller ve parola doğrulama (scrypt)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime

from sqlalchemy import func, select

from plakatanima.db.database import Database
from plakatanima.db.models import User, UserRole

DEFAULT_ADMIN = "admin"
DEFAULT_PASSWORD = "admin"
MIN_PASSWORD_LENGTH = 4

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    encode = base64.b64encode
    return (
        f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}$"
        f"{encode(salt).decode()}${encode(digest).decode()}"
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


class AuthError(ValueError):
    pass


class UserService:
    def __init__(self, db: Database) -> None:
        self._db = db

    def ensure_default_admin(self) -> bool:
        """Hiç kullanıcı yoksa ``admin``/``admin`` oluşturur (ilk girişte parola değişir)."""
        with self._db.session() as s:
            if s.scalar(select(func.count()).select_from(User)):
                return False
            s.add(
                User(
                    username=DEFAULT_ADMIN,
                    full_name="Yönetici",
                    password_hash=hash_password(DEFAULT_PASSWORD),
                    role=UserRole.ADMIN,
                    must_change_password=True,
                )
            )
            return True

    def list(self) -> list[User]:
        with self._db.session() as s:
            return list(s.scalars(select(User).order_by(User.username)))

    def get(self, username: str) -> User | None:
        with self._db.session() as s:
            return s.scalar(select(User).where(User.username == username.strip().lower()))

    def authenticate(self, username: str, password: str) -> User | None:
        with self._db.session() as s:
            user = s.scalar(select(User).where(User.username == username.strip().lower()))
            if user is None or not user.is_active:
                return None
            if not verify_password(password, user.password_hash):
                return None
            user.last_login = datetime.now().replace(microsecond=0)
            return user

    def create(
        self,
        username: str,
        password: str,
        *,
        role: UserRole = UserRole.OPERATOR,
        full_name: str = "",
        must_change_password: bool = False,
    ) -> User:
        username = username.strip().lower()
        if not username or not username.replace(".", "").replace("_", "").isalnum():
            raise AuthError("Kullanıcı adı yalnızca harf, rakam, '.' ve '_' içerebilir")
        self._check_password(password)
        with self._db.session() as s:
            if s.scalar(select(User).where(User.username == username)) is not None:
                raise AuthError(f"'{username}' kullanıcısı zaten var")
            user = User(
                username=username,
                full_name=full_name.strip(),
                password_hash=hash_password(password),
                role=UserRole(role),
                must_change_password=must_change_password,
            )
            s.add(user)
            s.flush()
            return user

    def update(
        self,
        user_id: int,
        *,
        full_name: str | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
    ) -> User:
        with self._db.session() as s:
            user = self._get(s, user_id)
            demoting = role is not None and UserRole(role) is not UserRole.ADMIN
            if (demoting or is_active is False) and user.role is UserRole.ADMIN:
                self._ensure_other_admin(s, user)
            if full_name is not None:
                user.full_name = full_name.strip()
            if role is not None:
                user.role = UserRole(role)
            if is_active is not None:
                user.is_active = is_active
            return user

    def set_password(self, user_id: int, password: str, *, must_change: bool = False) -> None:
        self._check_password(password)
        with self._db.session() as s:
            user = self._get(s, user_id)
            user.password_hash = hash_password(password)
            user.must_change_password = must_change

    def change_password(self, user_id: int, old_password: str, new_password: str) -> None:
        with self._db.session() as s:
            user = self._get(s, user_id)
            if not verify_password(old_password, user.password_hash):
                raise AuthError("Mevcut parola hatalı")
        if new_password == old_password:
            raise AuthError("Yeni parola eskisiyle aynı olamaz")
        self.set_password(user_id, new_password)

    def delete(self, user_id: int) -> None:
        with self._db.session() as s:
            user = self._get(s, user_id)
            if user.role is UserRole.ADMIN:
                self._ensure_other_admin(s, user)
            s.delete(user)

    @staticmethod
    def _get(s, user_id: int) -> User:
        user = s.get(User, user_id)
        if user is None:
            raise AuthError(f"Kullanıcı bulunamadı: {user_id}")
        return user

    @staticmethod
    def _ensure_other_admin(s, user: User) -> None:
        others = s.scalar(
            select(func.count()).where(
                User.role == UserRole.ADMIN, User.is_active.is_(True), User.id != user.id
            )
        )
        if not others:
            raise AuthError("Sistemde en az bir etkin yönetici kalmalı")

    @staticmethod
    def _check_password(password: str) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise AuthError(f"Parola en az {MIN_PASSWORD_LENGTH} karakter olmalı")
