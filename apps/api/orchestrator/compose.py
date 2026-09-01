"""
합성(compose)과 검증(verify_numbers) — 축 4 (담당: 정민)

여러 에이전트가 한 턴에 실행됐을 때 답변을 하나로 합칩니다.

  1. LLM 이 각 에이전트 답변을 사용자 메시지 흐름에 맞게 한 편으로 다듬는다 (draft).
  2. verify_numbers() 가 draft 에 등장하는 금액·퍼센트·날짜를 정규식으로 뽑아 원본
     agent_outputs(reply + data) 와 대조한다 — 코드 규칙. 1차는 문자열 포함 검사,
     실패 시 2차로 값 수준 비교(semantic): "3억 5천만원" ↔ "350,000,000원",
     "2026-02-28" ↔ "2026년 2월 28일" 처럼 표기만 다른 경우를 오탐에서 구제한다.
     양쪽 다 명확히 파싱될 때만 값으로 인정하고, 파싱이 안 되면 mismatch 로
     남긴다(fail-closed) — 미탐(틀린 숫자 통과)보다 오탐(멀쩡한 합성문 폐기)이 낫다.
  3. 하나라도 원문에 없으면 draft 를 버리고 각 에이전트 reply 를 그대로 이어붙인다
     (fallback_concat) + verification.ok=False 로 "⚠️ 확인필요" 배지를 띄우게 한다.

"숫자·법률 판단은 원문 그대로"가 프롬프트 약속이 아니라 코드로 강제되는 지점입니다.
LLM 을 못 쓰는 환경에서는 처음부터 이어붙이기(concat)로 가며, 이 경우는 원문 그대로
이므로 verification.ok=True 입니다.
"""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

from schemas import AgentOutput, VerificationResult

from . import registry
from .llm_policy import llm_enabled, llm_required

logger = logging.getLogger(__name__)

# 금액: 1,234,567원 / 3억 5천만원 / 5000만원 / 12.5억 / 1,000 (쉼표 숫자)
# "3억 5천만원" 같은 복합 표기는 한 토큰으로 잡는다. 단위 없는 끝자리 수는 바로 뒤에
# "원"이 붙을 때만 붙인다("1억 2345원") — 무관한 숫자("1억 2026년…")를 삼키지 않도록.
_RE_AMOUNT = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*(?:억|천만|백만|만|천)"
    r"(?:\s*\d[\d,]*(?:\.\d+)?\s*(?:억|천만|백만|만|천))*"
    r"(?:\s*\d[\d,]*(?:\.\d+)?\s*원|\s*원)?"
    r"|\d[\d,]*(?:\.\d+)?\s*원?"
)
# 퍼센트
_RE_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%")
# 날짜: 2026-08-28 / 2026.08.28 / 2026년 8월 28일 / 8월 28일
_RE_DATE = re.compile(
    r"\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{4}년\s*\d{1,2}월\s*\d{1,2}일|\d{1,2}월\s*\d{1,2}일"
)


def _normalize(text: str) -> str:
    return re.sub(r"[\s,]", "", text)


def _extract_typed(text: str) -> list[tuple[str, str]]:
    """(종류, 정규화된 토큰) 쌍으로 검증 대상 팩트를 뽑습니다.

    금액 정규식은 '3개월' 의 '3' 같은 것도 잡으므로, 단위(원/억/만…)나 쉼표·소수점이
    있거나 4자리 이상인 숫자만 금액으로 봅니다. 나머지 짧은 정수는 검증하지 않습니다
    (자녀 수, 순위 등은 원문 대조의 의미가 약합니다).
    """
    facts: list[tuple[str, str]] = []
    for m in _RE_DATE.finditer(text):
        facts.append(("date", _normalize(m.group())))
    for m in _RE_PERCENT.finditer(text):
        facts.append(("percent", _normalize(m.group())))
    for m in _RE_AMOUNT.finditer(text):
        raw = m.group()
        if text[m.end() :].lstrip().startswith("%"):
            continue  # 퍼센트의 숫자 부분 — percent 팩트로 이미 검증된다
        digits = re.sub(r"\D", "", raw)
        has_unit = bool(re.search(r"억|천만|백만|만|천|원", raw))
        if not has_unit and "," not in raw and "." not in raw and len(digits) < 4:
            continue
        facts.append(("amount", _normalize(raw)))
    return facts


def extract_facts(text: str) -> list[str]:
    """검증 대상이 되는 토큰(금액·퍼센트·날짜)을 정규화해서 뽑습니다."""
    return [fact for _, fact in _extract_typed(text)]


_UNIT_FACTORS = {
    "억": Decimal(10**8),
    "천만": Decimal(10**7),
    "백만": Decimal(10**6),
    "만": Decimal(10**4),
    "천": Decimal(10**3),
}
_RE_AMOUNT_CHUNK = re.compile(r"(\d+(?:\.\d+)?)(억|천만|백만|만|천)?")


def _parse_amount(fact: str) -> Optional[Decimal]:
    """정규화된 금액 토큰을 원 단위 값으로. 애매하면 None (fail-closed).

    "3억5천만원" → 350000000, "1,234,000원"(정규화 후 "1234000원") → 1234000.
    단위 없는 묶음은 마지막 자리(원 단위)에만 허용합니다.
    """
    text = fact[:-1] if fact.endswith("원") else fact
    total = Decimal(0)
    pos = 0
    while pos < len(text):
        m = _RE_AMOUNT_CHUNK.match(text, pos)
        if not m or m.end() == pos:
            return None
        try:
            number = Decimal(m.group(1))
        except InvalidOperation:
            return None
        unit = m.group(2)
        if unit is None and m.end() != len(text):
            return None
        total += number * (_UNIT_FACTORS[unit] if unit else Decimal(1))
        pos = m.end()
    return total


def _parse_percent(fact: str) -> Optional[Decimal]:
    try:
        return Decimal(fact.rstrip("%"))
    except InvalidOperation:
        return None


_RE_DATE_ISO = re.compile(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})")
_RE_DATE_KO = re.compile(r"(\d{4})년(\d{1,2})월(\d{1,2})일")
_RE_DATE_MD = re.compile(r"(\d{1,2})월(\d{1,2})일")


def _parse_date(fact: str) -> Optional[tuple[Optional[int], int, int]]:
    """정규화된 날짜 토큰을 (연, 월, 일)로. 연도 없는 표기는 연=None."""
    for pattern in (_RE_DATE_ISO, _RE_DATE_KO):
        m = pattern.fullmatch(fact)
        if m:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _RE_DATE_MD.fullmatch(fact)
    if m:
        return (None, int(m.group(1)), int(m.group(2)))
    return None


def _parse_fact(kind: str, fact: str):
    if kind == "amount":
        return _parse_amount(fact)
    if kind == "percent":
        return _parse_percent(fact)
    return _parse_date(fact)


def _source_parts(agent_outputs: list[AgentOutput]) -> list[str]:
    parts = [o.reply for o in agent_outputs]
    for o in agent_outputs:
        try:
            parts.append(json.dumps(o.data, ensure_ascii=False, default=str))
        except TypeError:
            parts.append(str(o.data))
    return parts


def _source_values(parts: list[str]) -> dict[str, set]:
    """원본에서 파싱 가능한 팩트를 값 집합으로 모읍니다 (2차 대조용)."""
    values: dict[str, set] = {
        "amount": set(),
        "percent": set(),
        "date": set(),
        "month_day": set(),
    }
    for part in parts:
        for kind, fact in _extract_typed(part):
            parsed = _parse_fact(kind, fact)
            if parsed is None:
                continue
            if kind == "date":
                year, month, day = parsed
                if year is not None:
                    values["date"].add(parsed)
                values["month_day"].add((month, day))
            else:
                values[kind].add(parsed)
    return values


def _matches_by_value(kind: str, fact: str, source_values: dict[str, set]) -> bool:
    parsed = _parse_fact(kind, fact)
    if parsed is None:
        return False
    if kind != "date":
        return parsed in source_values[kind]
    year, month, day = parsed
    if year is None:
        # draft 가 연도를 생략한 건 정보 누락일 뿐 조작이 아니다
        return (month, day) in source_values["month_day"]
    # draft 가 붙인 연도는 원본에 연도까지 있는 날짜와만 맞아야 한다
    return parsed in source_values["date"]


def verify_numbers(draft: str, agent_outputs: list[AgentOutput]) -> VerificationResult:
    """draft 의 금액·퍼센트·날짜가 전부 원본에 있으면 ok.

    1차: 정규화 문자열 포함 검사. 2차: 표기만 다른 경우를 값 비교로 구제
    ("3억 5천만원" ↔ "350,000,000원"). 어느 쪽으로도 확인 안 되면 mismatch.
    """
    parts = _source_parts(agent_outputs)
    source = _normalize("\n".join(parts))
    source_values = _source_values(parts)
    mismatches = [
        fact
        for kind, fact in _extract_typed(draft)
        if fact not in source and not _matches_by_value(kind, fact, source_values)
    ]
    # 중복 제거(순서 유지)
    seen: set[str] = set()
    unique = [m for m in mismatches if not (m in seen or seen.add(m))]
    return VerificationResult(ok=not unique, mode="synthesized", mismatches=unique)


def fallback_concat(agent_outputs: list[AgentOutput]) -> str:
    specs = registry.all_specs()
    sections: list[str] = []
    for o in agent_outputs:
        spec = specs.get(o.agent)
        title = (
            spec.description.split("(")[0].split("·")[0].strip()
            if spec
            else o.agent.value
        )
        sections.append(f"【{title}】\n{o.reply.strip()}")
    return "\n\n".join(sections)


# _llm_enabled 는 llm_policy 로 이동 (planner.py 와 중복 제거)


_SYNTH_SYSTEM = """당신은 가족 자산·상속 상담 서비스의 편집자입니다. 여러 전문 에이전트가
각자 작성한 답변을 받아, 사용자의 질문 흐름에 맞게 하나의 자연스러운 답변으로 정리합니다.

절대 규칙:
- 금액, 퍼센트, 날짜, 기한, 법률 판정(유효/무효, 가능/불가능)은 원문의 표기를 한 글자도
  바꾸지 말고 그대로 옮기세요. 새 숫자를 계산하거나 추정하지 마세요.
- 원문에 없는 내용을 추가하지 마세요. 원문을 빠뜨리지도 마세요.
- 각 에이전트의 주제가 구분되도록 소제목을 붙이되, 전체는 하나의 답변처럼 읽혀야 합니다.
- 한국어 존댓말, 마크다운 최소화."""


def llm_synthesize(
    agent_outputs: list[AgentOutput], user_message: str
) -> Optional[str]:
    """LLM 합성 초안. 못 쓰는 환경이거나 실패하면 None."""
    if not llm_enabled():
        return None
    try:
        from llm import claude

        specs = registry.all_specs()
        blocks = []
        for o in agent_outputs:
            spec = specs.get(o.agent)
            desc = spec.description if spec else o.agent.value
            blocks.append(f"### {o.agent.value} — {desc}\n{o.reply.strip()}")
        user_text = (
            f"사용자 질문:\n{user_message}\n\n에이전트 답변들:\n\n"
            + "\n\n".join(blocks)
        )
        return claude.complete(
            system=_SYNTH_SYSTEM,
            messages=[{"role": "user", "content": user_text}],
            max_tokens=4000,
            effort="low",
        )
    except Exception:  # noqa: BLE001
        if llm_required():
            raise
        logger.warning("합성 LLM 호출 실패 — 이어붙이기로 폴백", exc_info=True)
        return None


def compose(
    agent_outputs: list[AgentOutput], user_message: str
) -> tuple[str, VerificationResult]:
    """(reply, verification). 에이전트 1개면 원문 그대로."""
    if len(agent_outputs) == 1:
        return agent_outputs[0].reply, VerificationResult(ok=True, mode="single")

    draft = llm_synthesize(agent_outputs, user_message)
    if not draft:
        return fallback_concat(agent_outputs), VerificationResult(
            ok=True, mode="concat"
        )

    verified = verify_numbers(draft, agent_outputs)
    if not verified.ok:
        logger.warning(
            "합성문 숫자 검증 실패 %s — 원문 이어붙이기로 폴백", verified.mismatches
        )
        return fallback_concat(agent_outputs), VerificationResult(
            ok=False, mode="concat_after_failure", mismatches=verified.mismatches
        )
    return draft, verified
