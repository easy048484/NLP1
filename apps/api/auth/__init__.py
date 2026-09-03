"""회원가입·로그인 (인증).

가족관계 그래프·재무 프로필처럼 민감한 개인정보를 다루므로, family_graph를
계정에 묶어 "본인만 조회·수정"할 수 있게 하는 최소 인증 계층입니다.

- `router`: /auth/register, /auth/login, /auth/me
- `get_current_user` / `get_current_user_optional`: 다른 라우터가 요청자를
  식별할 때 쓰는 FastAPI 의존성.
"""

from .dependencies import (
    get_current_user,
    get_current_user_id_optional,
    get_current_user_optional,
)
from .models import User
from .router import router

__all__ = [
    "User",
    "get_current_user",
    "get_current_user_id_optional",
    "get_current_user_optional",
    "router",
]
