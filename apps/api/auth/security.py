"""비밀번호 해싱 + 액세스 토큰(JWT) 발급·검증.

설계 판단
--------
- **비밀번호 해시는 stdlib `hashlib.pbkdf2_hmac`** 를 씁니다. bcrypt/argon2는
  C 확장이라 `psycopg2-binary` 처럼 파이썬 버전별 휠 문제가 재발할 수 있어,
  빌드 리스크가 없는 순수 stdlib 경로를 택했습니다. OWASP 권고(PBKDF2-HMAC-
  SHA256, 반복 60만회 이상)를 충족합니다.
- **토큰은 JWT(HS256)** — `PyJWT`(순수 파이썬). 서버가 상태를 들고 있지 않아도
  되도록(무상태) 서명 토큰을 씁니다. 세션 저장소(orchestrator)는 대화 상태
  전용이라 인증까지 얹지 않습니다.
- **시크릿은 `JWT_SECRET` 환경변수에서만** 읽습니다. 없으면 개발용 기본값을
  쓰되 경고 로그를 남깁니다 — 배포 환경(Vercel/Railway)에서는 반드시 주입해야
  합니다(.env.example 참고).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

logger = logging.getLogger(__name__)

_PBKDF2_ALGORITHM = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 600_000
_TOKEN_ALGORITHM = "HS256"
#: 토큰 유효기간. 상속 절차가 몇 주 이어질 수 있어 넉넉하게 잡되, 무한은 아님.
_TOKEN_TTL = timedelta(days=14)

_DEV_SECRET = "dev-only-insecure-secret-change-me"


def _secret() -> str:
    value = os.getenv("JWT_SECRET", "").strip()
    if value:
        return value
    logger.warning(
        "JWT_SECRET이 비어 있어 개발용 기본 시크릿을 사용합니다. "
        "배포 환경에서는 반드시 JWT_SECRET을 설정하세요."
    )
    return _DEV_SECRET


# --------------------------------------------------------------------- 비밀번호


def hash_password(plain: str) -> str:
    """평문 비밀번호를 "pbkdf2_sha256$<iter>$<salt_b64>$<hash_b64>" 로 변환합니다."""
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256", plain.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return "$".join(
        [
            _PBKDF2_ALGORITHM,
            str(_PBKDF2_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(derived).decode("ascii"),
        ]
    )


def verify_password(plain: str, stored: str) -> bool:
    """평문이 저장된 해시와 일치하는지. 형식이 깨졌으면 조용히 False."""
    try:
        algorithm, iterations_text, salt_b64, hash_b64 = stored.split("$")
        if algorithm != _PBKDF2_ALGORITHM:
            return False
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False

    candidate = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)


# ----------------------------------------------------------------------- 토큰


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + _TOKEN_TTL,
    }
    return jwt.encode(payload, _secret(), algorithm=_TOKEN_ALGORITHM)


def decode_access_token(token: str) -> Optional[str]:
    """토큰에서 user_id(sub)를 꺼냅니다. 만료·서명 오류·형식 오류면 None."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_TOKEN_ALGORITHM])
    except jwt.PyJWTError:
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None
