"""FastAPI 인증 의존성.

- `get_db`: 요청 하나짜리 DB 세션 (DB 미설정이면 503).
- `get_current_user`: Authorization: Bearer <token> 에서 사용자를 식별.
  없거나 토큰이 유효하지 않으면 401.
- `get_current_user_optional`: 같은 로직이되, 없으면 None(익명 허용 경로용).
- `get_current_user_id_optional`: 사용자 id만 돌려주되 DB가 없어도 503을 내지
  않는 판(/chat 처럼 DB 없이도 동작해야 하는 경로용).
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


def get_current_user_id_optional(
    authorization: Optional[str] = Header(default=None),
) -> Optional[str]:
    """요청자의 사용자 id. 비로그인·토큰 무효·DB 미설정이면 모두 None.

    get_current_user_optional 과 갈라놓은 이유는 get_db 때문입니다. 그쪽은
    DATABASE_URL 이 없으면 503 을 던지는데, /chat 은 DB 없이도(인메모리 세션)
    끝에서 끝까지 동작해야 하는 경로입니다. 인증을 붙였다는 이유로 DB 없는
    환경(CI, 로컬 mock)에서 /chat 이 죽으면 안 됩니다.

    세션 저장소가 필요로 하는 건 id 하나뿐이라 User 객체를 돌려주지 않습니다 —
    요청 수명을 넘겨 쓸 ORM 객체를 들고 다니지 않기 위해서이기도 합니다.
    """
    token = _token_from_header(authorization)
    if token is None:
        return None
    user_id = decode_access_token(token)
    if user_id is None:
        return None
    try:
        get_engine()
    except DatabaseNotConfigured:
        # DB가 없으면 사용자를 확인할 방법이 없습니다. 확인되지 않은 토큰으로
        # 남의 세션을 소유하게 두느니 익명으로 취급합니다.
        return None
    with session_scope() as db:
        user = repository.get_user_by_id(db, user_id)
        return user.id if user is not None else None
