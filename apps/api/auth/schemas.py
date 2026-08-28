"""auth API 요청/응답 스키마 (pydantic)."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

# 아주 느슨한 이메일 형식 검사 — pydantic EmailStr은 email-validator 의존성이
# 필요해서, 빌드 리스크를 피하려고 직접 정규식으로만 거릅니다(로컬 파트 @ 도메인
# . tld). 실제 도달 가능성 검증은 하지 않습니다(MVP 범위).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=100)

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL_RE.match(value):
            raise ValueError("이메일 형식이 올바르지 않습니다.")
        return value


class LoginIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=128)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class UserOut(BaseModel):
    id: str
    email: str
    name: str

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
