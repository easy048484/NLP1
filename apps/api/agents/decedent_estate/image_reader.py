"""
유언장 사진 판독 (1단계, CLAUDE.md 절대 원칙 4 예외 조항 참고).

사용자가 유언장 사진을 올리면 성명·주소·작성연월일·날인(도장/지장) 4개
필드를 값+확신도(confidence) 형태로 추출한다. 이 모듈은 "입력 보조"만
담당한다 — 요건 충족 여부·유효/무효 판정은 절대 하지 않으며, 반환값은
호출부(agent.py)가 기존 requirement_checker.py 파이프라인에 텍스트로
재구성해 넣는 재료일 뿐이다.

⚠️ 자서(전문 자서, "본인이 직접 썼는가") 는 이 모듈의 추출 대상이 절대
아니다 — 필적 감정 영역이라 사진으로 판단할 수 없고, LLM이 판정하게 해서도
안 된다(설계 방침 F). handwriting 요건은 원래부터 requirements.json 에서
`extraction_type: "user_confirm"`이라 이 기능 이전에도 항상 사용자에게
직접 물었다 — 이 모듈은 그 경로를 그대로 둔다(새로 만들 것 없음).

⚠️ 원본 이미지는 저장하지 않는다. 이 함수는 base64 데이터를 받아 Anthropic
API에 전달하고, 반환하는 즉시 그 데이터를 들고 있지 않는다(호출 스택을
벗어나면 참조가 사라진다) — DecedentState 어디에도 이미지 필드가 없다
(state.py 참고).

확신도 3단(설계 방침 E):
- "high": 명확히 읽힘 → 추출값을 그대로 채운다(질문 없음)
- "low": 애매함 → "이렇게 읽었는데 맞습니까?" 확인 질문
- "none": 못 읽음 → 사용자가 직접 입력

날인(seal)은 "도장/지장이 찍혀 있는 것으로 보이는가"라는 순수 시각적 사실
관찰이라 자서와 다르다 — 판독 대상에 포함한다. value 는 requirements.json
의 seal 조건 id 중 "seal_or_fingerprint" | "absent" 로만 분류한다
("signature_only"와의 구분은 미세해 사진만으로 신뢰하기 어려워 제외 —
애매하면 confidence를 낮춰 기존 seal_answer user_confirm 질문으로 넘긴다).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .llm_client import (
    _client,
    _load_json_response,
    _validated_name,
    _validated_short_text,
)

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 500
_TIMEOUT_SECONDS = 20.0

# Anthropic Messages API가 받는 이미지 포맷 (공식 문서 기준, 2026-08-25 확인).
# 오디오는 API 자체가 지원하지 않아 이 기능의 대상이 아니다(녹음은 범위 밖).
SUPPORTED_MEDIA_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/gif", "image/webp"}
)

_VALID_CONFIDENCE_VALUES = frozenset({"high", "low", "none"})
_VALID_SEAL_VALUES = frozenset({"seal_or_fingerprint", "absent"})

# 추출 대상 4필드. "handwriting"(자서)은 의도적으로 없다 — 위 모듈 docstring 참고.
PHOTO_FIELD_IDS = ("name", "address", "date", "seal")

_WILL_PHOTO_SYSTEM_PROMPT = (
    "너는 자필증서 유언장 사진에서 아래 4개 항목만 값을 추출하는 도구다.\n"
    "절대 판정하지 마라 — 요건 충족 여부, 유효/무효 여부, 필적이 누구의 "
    "것인지는 이 도구의 역할이 아니고 다른 시스템/사람이 처리한다. 너는 오직 "
    "사진에 무엇이 적혀 있는지만 읽는다.\n"
    "\n"
    "각 항목마다 값(value)과 확신도(confidence)를 함께 답하라. confidence는 "
    "다음 세 값 중 하나여야 한다:\n"
    '- "high": 글자가 선명해서 확실하게 읽었다\n'
    '- "low": 흐릿하거나 필체가 모호해 추측이 섞였다\n'
    '- "none": 아예 읽을 수 없거나 사진에 해당 내용이 없다 (이 경우 value는 '
    "반드시 null)\n"
    "\n"
    "4개 항목:\n"
    "1. name: 유언자 본인의 성명. 재산을 받는 사람(수증자·상속인 등)의 "
    "이름과 혼동하지 마라.\n"
    "2. address: 유언자 본인의 주소. 상속·증여 대상 부동산 소재지와 "
    "혼동하지 마라. 원문에 적힌 그대로 옮겨 적어라.\n"
    "3. date: 유언장을 작성한 연월일(작성일). 원문에 적힌 그대로 옮겨 "
    "적어라 — 숫자로 바꾸거나 다른 형식으로 고치지 마라.\n"
    "4. seal: 도장 또는 지장(손도장)이 찍혀 있는 것으로 보이면 "
    '"seal_or_fingerprint", 안 보이면 "absent". 이 항목은 value가 이 '
    "두 값 중 하나여야 하며 null이 될 수 없다 — 판단이 애매하면 값은 "
    '적당히 고르되 confidence를 "low"로 낮춰라.\n'
    "\n"
    "반드시 아래 JSON 형식으로만 답하라. 다른 설명이나 문장을 절대 "
    "덧붙이지 마라.\n"
    "{\n"
    '  "name": {"value": "홍길동" 또는 null, "confidence": "high"|"low"|"none"},\n'
    '  "address": {"value": "..." 또는 null, "confidence": "high"|"low"|"none"},\n'
    '  "date": {"value": "..." 또는 null, "confidence": "high"|"low"|"none"},\n'
    '  "seal": {"value": "seal_or_fingerprint"|"absent", '
    '"confidence": "high"|"low"|"none"}\n'
    "}"
)


def _validated_field(raw: Any, *, validator) -> tuple[Optional[str], str]:
    """{"value":..., "confidence":...} 하나를 검증해 (value, confidence)로 돌려준다.

    confidence 가 스키마를 안 지켰다는 것은 응답 전체를 신뢰하기 어렵다는
    신호이므로, 이 경우 value 도 함께 버린다("없음"과 동일하게 (None, "none")) —
    애매한 응답을 신뢰해서 상위 파이프라인에 잘못된 확신을 주지 않는다.
    """
    if not isinstance(raw, dict):
        return None, "none"
    confidence = raw.get("confidence")
    if confidence not in _VALID_CONFIDENCE_VALUES:
        return None, "none"
    value = validator(raw.get("value"))
    if value is None:
        confidence = "none"
    return value, confidence


def _validated_seal_field(raw: Any) -> tuple[Optional[str], str]:
    if not isinstance(raw, dict):
        return None, "none"
    confidence = raw.get("confidence")
    if confidence not in _VALID_CONFIDENCE_VALUES:
        return None, "none"
    value = raw.get("value")
    if value not in _VALID_SEAL_VALUES:
        return None, "none"
    return value, confidence


def _parse_photo_fields(raw_response_text: str) -> Optional[dict[str, dict[str, Any]]]:
    parsed = _load_json_response(raw_response_text)
    if not isinstance(parsed, dict):
        return None

    name_value, name_conf = _validated_field(
        parsed.get("name"), validator=_validated_name
    )
    address_value, address_conf = _validated_field(
        parsed.get("address"), validator=_validated_short_text
    )
    date_value, date_conf = _validated_field(
        parsed.get("date"), validator=_validated_short_text
    )
    seal_value, seal_conf = _validated_seal_field(parsed.get("seal"))

    return {
        "name": {"value": name_value, "confidence": name_conf},
        "address": {"value": address_value, "confidence": address_conf},
        "date": {"value": date_value, "confidence": date_conf},
        "seal": {"value": seal_value, "confidence": seal_conf},
    }


def extract_will_photo_fields(
    image_base64: str, media_type: str
) -> Optional[dict[str, dict[str, Any]]]:
    """유언장 사진에서 성명/주소/작성연월일/날인 4필드를 값+확신도로 추출한다.

    반환: {"name": {"value": str|None, "confidence": "high"|"low"|"none"},
           "address": {...}, "date": {...},
           "seal": {"value": "seal_or_fingerprint"|"absent"|None, "confidence": ...}}
    또는 (키 없음/지원 안 하는 포맷/네트워크 오류/타임아웃/형식 오류 시) None —
    호출부는 이 경우 사용자에게 직접 입력을 요청해야 한다(요건 판정을 막지 않음).

    이미지 데이터 자체는 이 함수 호출이 끝나면 참조가 남지 않는다 — 저장하지 않는다.
    """
    if media_type not in SUPPORTED_MEDIA_TYPES:
        logger.warning("사진 판독 실패 (지원하지 않는 media_type)")
        return None

    client = _client()
    if client is None:
        return None

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_WILL_PHOTO_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_base64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "이 유언장 사진에서 위 4개 항목을 추출해줘.",
                        },
                    ],
                }
            ],
            timeout=_TIMEOUT_SECONDS,
        )
        return _parse_photo_fields(response.content[0].text)
    except Exception as exc:
        logger.warning("사진 판독 실패 (%s)", type(exc).__name__)
        return None
