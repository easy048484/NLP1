"""FastAPI 인증 의존성.

- `get_db`: 요청 하나짜리 DB 세션 (DB 미설정이면 503).
- `get_current_user`: Authorization: Bearer <token> 에서 사용자를 식별.
  없거나 토큰이 유효하지 않으면 401.
- `get_current_user_optional`: 같은 로직이되, 없으면 None(익명 허용 경로용).
"""

from __future__ import annotations

from typing import Iterator, Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from db.base import DatabaseNotConfigured, get_engine, session_scope

from . import repository
from .models import User
from .security import decode_access_token

_UNAUTHORIZED = HTTPException(
    status_code=401,
    detail="로그인이 필요합니다.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_db() -> Iterator[Session]:
    try:
        get_engine()
    except DatabaseNotConfigured as exc:
        raise HTTPException(
            status_code=503, detail="DATABASE_URL이 설정돼 있지 않습니다."
        ) from exc
    with session_scope() as db:
        yield db


def _token_from_header(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def get_current_user_optional(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    token = _token_from_header(authorization)
    if token is None:
        return None
    user_id = decode_access_token(token)
    if user_id is None:
        return None
    return repository.get_user_by_id(db, user_id)


def get_current_user(
    user: Optional[User] = Depends(get_current_user_optional),
) -> User:
    if user is None:
        raise _UNAUTHORIZED
    return user
