"""회원가입·로그인 REST API.

- POST /auth/register : 가입 후 곧바로 로그인 상태로(토큰 발급).
- POST /auth/login    : 이메일+비밀번호 → 토큰.
- GET  /auth/me       : 현재 토큰의 사용자 정보.

비밀번호는 security.hash_password(PBKDF2)로만 저장하고, 로그인 실패 시
"이메일이 없다 / 비밀번호가 틀리다"를 구분하지 않습니다(계정 존재 여부 노출
방지).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import repository
from .dependencies import get_current_user, get_db
from .models import User
from .schemas import LoginIn, RegisterIn, TokenOut, UserOut
from .security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id),
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=TokenOut, status_code=201)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> TokenOut:
    if repository.get_user_by_email(db, payload.email) is not None:
        raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다.")
    user = repository.create_user(
        db,
        email=payload.email,
        password_hash=hash_password(payload.password),
        name=payload.name,
    )
    return _token_response(user)


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    user = repository.get_user_by_email(db, payload.email)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다."
        )
    return _token_response(user)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)
