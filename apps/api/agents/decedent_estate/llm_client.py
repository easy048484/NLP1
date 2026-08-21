"""
LLM 추출 클라이언트 (CLAUDE.md 빌드 순서 4단계).

네 가지 추출을 담당한다:
1. extract_testator_name — 자필증서 유언자 본인 성명 단일 추출 (requirement_checker
   에서 정규식이 못 찾았을 때만 호출).
2. extract_recording_fields — 녹음 유언(§1067) 대본에서 5개 항목
   (유언자 성명/증인 성명/구술 연월일/재산 처분 의사/증인의 정확함 확인)을
   한 번의 호출로 함께 추출 (recording_checker에서 정규식이 5개 중 하나라도
   못 찾았을 때만 호출 — 항목별로 나눠 부르지 않는다, 비용/지연 절감).
3. extract_will_date — 자필증서 유언장 작성 연월일 "문자열" 단일 추출
   (requirement_checker 에서 정규식이 날짜를 전혀 못 찾았을 때만 호출).
   이 함수는 값만 반환하고, day_missing/verbal_specified 같은 등급은
   호출부가 date_parser.parse_dates 에 그 문자열을 다시 통과시켜 규칙
   엔진으로 매긴다 — LLM이 case 를 직접 결정하지 않는다. 여러 날짜가
   섞여 있어 작성일을 "선별"해야 하는 경우(multiple_dates_mixed)는
   이 함수의 대상이 아니다 — 그건 절 추출이 아니라 사실 판단에 가까워
   신뢰 모델이 다르고, 잘못 선별해도 형식상 결과가 나와 실패가 조용히
   묻힐 위험이 있다 (docs/known_limitations.md 3-4).
4. extract_will_address — 자필증서 유언자 본인 주소 "문자열" 단일 추출
   (requirement_checker 에서 정규식이 주소를 전혀 못 찾았을 때만 호출).
   이 함수도 값만 반환하고, full_address/city_district_only 등급은
   호출부가 그 문자열을 주소 판별 정규식에 다시 통과시켜 매긴다.

⚠️ CLAUDE.md 절대 원칙:
1. 판정은 하지 않는다. 이 모듈은 값/사실 여부만 추출한다 — 요건 충족 여부·
   유효/무효 판단은 requirement_checker.py·recording_checker.py +
   rules/requirements.json 의 몫이며, 이 모듈이 반환한 값도 그 판정
   파이프라인을 그대로 통과한다.
4. 호출부(requirement_checker.py, recording_checker.py)가 masking.mask_text()
   를 거친 텍스트만 이 함수들에 넘긴다는 전제로 동작한다. 이 모듈 자체는
   마스킹을 하지 않는다.
6. 요청/응답을 저장하지 않는다. 실패 시에도 원문이 담긴 예외 메시지를
   로깅하지 않고 그냥 None 을 반환한다 — 호출부가 정규식 결과로 폴백한다.

API 키는 팀 공용 키(.env 의 ANTHROPIC_API_KEY)를 쓴다. 키가 없거나, 네트워크
오류·타임아웃·응답 형식 오류가 나면 예외를 던지지 않고 조용히 None 을 반환한다.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

import anthropic

_MODEL = "claude-haiku-4-5-20251001"
_TIMEOUT_SECONDS = 8.0
_NAME_MAX_TOKENS = 64
_RECORDING_MAX_TOKENS = 300
_DATE_MAX_TOKENS = 64
_ADDRESS_MAX_TOKENS = 100

# LLM이 돌려준 이름이 정말 "이름처럼" 생겼는지 최소한으로 검증한다 — 응답 형식
# 오류나 프롬프트 인젝션성 텍스트를 그대로 신뢰하지 않기 위한 방어선.
_VALID_NAME_RE = re.compile(r"^[가-힣]{2,10}$")

# 날짜·주소는 이름과 달리 표기가 너무 다양해 형식 정규식으로 검증할 수 없다.
# 대신 응답이 빈 문자열이거나 비정상적으로 길면(프롬프트 인젝션성 텍스트 등)
# 버린다 — 실제 날짜·주소 문구가 이 길이를 넘을 일은 거의 없다.
_MAX_SHORT_TEXT_LENGTH = 120

_TESTATOR_NAME_SYSTEM_PROMPT = (
    "너는 자필증서 유언장 텍스트에서 유언자 본인의 성명만 추출하는 도구다.\n"
    "절대 판정하지 마라 — 요건 충족 여부, 유효/무효 여부는 이 도구의 역할이 아니고 "
    "다른 시스템이 처리한다. 너는 오직 값 추출만 한다.\n"
    "재산을 받는 사람(수증자·상속인·배우자·자녀 등)의 이름과, 유언장을 작성한 "
    "유언자 본인의 이름을 혼동하지 마라. 유언자 본인의 이름은 보통 '유언자', "
    "'나는' 같은 표현과 함께 나오거나 문서 하단 서명란에 등장한다.\n"
    "반드시 아래 JSON 형식으로만 답하라. 다른 설명이나 문장을 절대 덧붙이지 마라.\n"
    '유언자 이름을 찾았으면: {"name": "홍길동"}\n'
    '찾을 수 없으면: {"name": null}'
)

_RECORDING_SYSTEM_PROMPT = (
    "너는 녹음 유언(구술을 받아쓴 대본) 텍스트에서 아래 5개 항목의 사실 여부만 "
    "확인하는 도구다.\n"
    "절대 판정하지 마라 — 요건 충족 여부, 유효/무효 여부는 이 도구의 역할이 아니고 "
    "다른 시스템이 처리한다. 너는 오직 사실 확인·값 추출만 한다.\n"
    "\n"
    "대본에는 여러 화자가 섞여 있을 수 있다. 누가 한 말인지 반드시 구분하라:\n"
    "- 유언자: 유언을 남기는 본인. 재산을 처분(상속·증여 등)하겠다는 의사를 말하는 사람.\n"
    "- 증인: 유언자의 말이 정확하다는 것과 자기 이름을 구술하는 사람.\n"
    "- 수증자(재산을 받는 사람, 예: 장남·배우자·자녀)는 유언자도 증인도 아니다 — "
    "수증자의 이름을 유언자나 증인 이름으로 착각하지 마라.\n"
    "\n"
    "반드시 아래 JSON 형식으로만 답하라. 다른 설명이나 문장을 절대 덧붙이지 마라.\n"
    "{\n"
    '  "testator_name": 유언자 본인 이름 문자열 또는 찾지 못했으면 null,\n'
    '  "witness_name": 증인 이름 문자열 또는 찾지 못했으면 null,\n'
    '  "date_text": 구술된 연월일 원문 문자열(예: "2026년 5월 3일") 또는 '
    "찾지 못했으면 null,\n"
    '  "has_disposition_intent": 유언자가 재산을 처분하겠다는 의사를 말했으면 '
    "true, 아니면 false,\n"
    '  "has_witness_accuracy": 증인이 유언 내용이 정확하다는 취지로 확인하는 '
    "말을 했으면 true, 아니면 false\n"
    "}"
)

_WILL_DATE_SYSTEM_PROMPT = (
    "너는 자필증서 유언장 텍스트에서 유언장을 작성한 연월일(작성일)이 적힌 "
    "부분만 원문 그대로 찾아내는 도구다.\n"
    "절대 판정하지 마라 — 일(日)이 빠졌는지, 날짜가 특정 가능한지 같은 판단은 "
    "이 도구의 역할이 아니고 다른 시스템이 처리한다. 너는 오직 값 추출만 한다.\n"
    "본문에는 작성일 외에도 다른 날짜(예: 재산 취득일, 과거 사건, 기념일 등)가 "
    "함께 등장할 수 있다. 그런 날짜가 두 개 이상 섞여 있어 어느 것이 작성일인지 "
    "애매하면 찾지 못한 것으로 처리하라 — 추측해서 하나를 고르지 마라.\n"
    "찾은 날짜는 원문에 적힌 그대로 옮겨 적어라. 숫자로 바꾸거나 다른 형식으로 "
    "고치지 마라.\n"
    "반드시 아래 JSON 형식으로만 답하라. 다른 설명이나 문장을 절대 덧붙이지 마라.\n"
    '작성일을 찾았으면: {"date_text": "2026년 5월 3일"}\n'
    '찾을 수 없거나 애매하면: {"date_text": null}'
)

_WILL_ADDRESS_SYSTEM_PROMPT = (
    "너는 자필증서 유언장 텍스트에서 유언자 본인의 주소가 적힌 부분만 원문 "
    "그대로 찾아내는 도구다.\n"
    "절대 판정하지 마라 — 주소가 번지까지 온전한지, 시·구 수준까지만인지 같은 "
    "판단은 이 도구의 역할이 아니고 다른 시스템이 처리한다. 너는 오직 값 추출만 "
    "한다.\n"
    "본문에는 유언자 본인 주소 외에도 상속·증여하는 부동산의 소재지가 함께 "
    "등장할 수 있다. 재산을 받는 사람의 주소나 부동산 소재지를 유언자 본인 "
    "주소와 혼동하지 마라 — 유언장을 작성한 유언자 본인이 사는 곳만 찾아라.\n"
    "찾은 주소는 원문에 적힌 그대로 옮겨 적어라. 다른 형식으로 고치지 마라.\n"
    "반드시 아래 JSON 형식으로만 답하라. 다른 설명이나 문장을 절대 덧붙이지 마라.\n"
    '유언자 본인 주소를 찾았으면: {"address_text": "서울특별시 강남구 테헤란로 123, 45동 678호"}\n'
    '찾을 수 없으면: {"address_text": null}'
)


def _client() -> Optional[anthropic.Anthropic]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def _validated_name(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not _VALID_NAME_RE.match(value):
        return None
    return value


def _parse_name(raw_response_text: str) -> Optional[str]:
    parsed = json.loads(raw_response_text.strip())
    name = parsed.get("name") if isinstance(parsed, dict) else None
    return _validated_name(name)


def _validated_short_text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > _MAX_SHORT_TEXT_LENGTH:
        return None
    return value


def _parse_will_date(raw_response_text: str) -> Optional[str]:
    parsed = json.loads(raw_response_text.strip())
    date_text = parsed.get("date_text") if isinstance(parsed, dict) else None
    return _validated_short_text(date_text)


def _parse_will_address(raw_response_text: str) -> Optional[str]:
    parsed = json.loads(raw_response_text.strip())
    address_text = parsed.get("address_text") if isinstance(parsed, dict) else None
    return _validated_short_text(address_text)


def _parse_recording_fields(raw_response_text: str) -> Optional[dict[str, Any]]:
    parsed = json.loads(raw_response_text.strip())
    if not isinstance(parsed, dict):
        return None

    date_text = parsed.get("date_text")
    if not isinstance(date_text, str) or not date_text.strip():
        date_text = None
    else:
        date_text = date_text.strip()

    return {
        "testator_name": _validated_name(parsed.get("testator_name")),
        "witness_name": _validated_name(parsed.get("witness_name")),
        "date_text": date_text,
        "has_disposition_intent": parsed.get("has_disposition_intent") is True,
        "has_witness_accuracy": parsed.get("has_witness_accuracy") is True,
    }


def extract_testator_name(masked_text: str) -> Optional[str]:
    """마스킹된 유언장 텍스트에서 유언자 본인 성명을 LLM으로 추출한다.

    호출부(requirement_checker.extract_name_with_fallback)가 정규식으로
    이름을 못 찾았을 때만(fallback) 이 함수를 부른다. 이 함수 자체는 성공/실패를
    구분하지 않고 항상 str(찾음) | None(못 찾음 또는 실패) 만 반환한다.
    """
    client = _client()
    if client is None:
        return None

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_NAME_MAX_TOKENS,
            system=_TESTATOR_NAME_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": masked_text}],
            timeout=_TIMEOUT_SECONDS,
        )
        return _parse_name(response.content[0].text)
    except Exception:
        # 네트워크 오류·타임아웃·응답 형식 오류 등 어떤 이유든 정규식 폴백으로
        # 넘긴다. 원문이 섞일 수 있는 예외 메시지는 로깅하지 않는다.
        return None


def extract_will_date(masked_text: str) -> Optional[str]:
    """마스킹된 유언장 텍스트에서 작성 연월일 문자열을 LLM으로 추출한다.

    호출부(requirement_checker.extract_date_with_fallback)가 정규식으로
    날짜를 전혀 못 찾았을 때만(fallback) 이 함수를 부른다. 반환값은 항상
    "원문 그대로의 날짜 문자열"이며, day_missing/verbal_specified 같은 등급은
    호출부가 date_parser.parse_dates 로 다시 매긴다 — 이 함수는 case 를
    직접 정하지 않는다.
    """
    client = _client()
    if client is None:
        return None

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_DATE_MAX_TOKENS,
            system=_WILL_DATE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": masked_text}],
            timeout=_TIMEOUT_SECONDS,
        )
        return _parse_will_date(response.content[0].text)
    except Exception:
        return None


def extract_will_address(masked_text: str) -> Optional[str]:
    """마스킹된 유언장 텍스트에서 유언자 본인 주소 문자열을 LLM으로 추출한다.

    호출부(requirement_checker.extract_address_with_fallback)가 정규식으로
    주소를 전혀 못 찾았을 때만(fallback) 이 함수를 부른다. 반환값은 항상
    "원문 그대로의 주소 문자열"이며, full_address/city_district_only 같은
    등급은 호출부가 주소 판별 정규식으로 다시 매긴다.
    """
    client = _client()
    if client is None:
        return None

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_ADDRESS_MAX_TOKENS,
            system=_WILL_ADDRESS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": masked_text}],
            timeout=_TIMEOUT_SECONDS,
        )
        return _parse_will_address(response.content[0].text)
    except Exception:
        return None


def extract_recording_fields(masked_text: str) -> Optional[dict[str, Any]]:
    """마스킹된 녹음 유언 대본에서 5개 항목을 한 번의 호출로 함께 추출한다.

    호출부(recording_checker.check_recording_requirements)가 정규식으로
    5개 항목 중 하나라도 못 찾았을 때만 이 함수를 부른다 — 항목별로 따로
    부르지 않고 대본 전체를 한 번만 보내 5개를 함께 받는다.

    반환: {"testator_name", "witness_name", "date_text",
           "has_disposition_intent", "has_witness_accuracy"} 또는
    (키 없음/네트워크 오류/타임아웃/형식 오류 시) None — 이 경우 호출부는
    아직 못 찾은 항목을 그대로 정규식의 absent 결과로 둔다.
    """
    client = _client()
    if client is None:
        return None

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_RECORDING_MAX_TOKENS,
            system=_RECORDING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": masked_text}],
            timeout=_TIMEOUT_SECONDS,
        )
        return _parse_recording_fields(response.content[0].text)
    except Exception:
        return None
