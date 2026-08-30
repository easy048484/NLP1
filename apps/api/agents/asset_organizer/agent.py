"""
자산 목록 정리(asset_inventory) 에이전트 — 체크리스트 흐름만 담당.

⚠️ develop 기준 재작업 메모: 예전 세션들에서는 이 에이전트 하나가 "자산·부채
체크리스트"와 "은퇴 후 자금 시뮬레이션"을 모두 했었다. develop의 실제 계획은
이 둘을 별개 에이전트로 나누는 것이었다(spec.py 참고 — asset_organizer는
produces=["asset_inventory"], retirement_planner는 produces=["retirement_gap"]).
그래서 시뮬레이션 부분(engine.py/engine_models.py/adapter.py/format_utils.py)은
agents/retirement_planner/로 그대로 옮겼고, 이 파일에는 체크리스트 흐름만
남았다.

흐름: 예금/주식/펀드/부동산/부채/보험 카테고리를 체크리스트로 모은다. 유형은
알지만 금액이 없는 항목은 임의로 0을 채우지 않고 금액만 콕 집어 되묻는다
(extractor.py의 "조용한 실패 금지" 원칙 그대로) — 단, 보험은 예외로 금액
없이도 확인된 것으로 처리한다(추출기 쪽 기존 원칙 그대로, 아래
_merge_extraction 참고). 부채는 remaining_balance가 확인된 뒤,
monthly_payment/end_age가 비어 있으면 한 번만(강제로 캐묻지 않고) 후속
질문을 던진다 — 답을 안 하거나 애매하면 재질문 없이 단순 모드로 남긴다.
퇴직연금도 완전히 같은 패턴으로, 확인되면 수령 방식을 한 번만 후속
질문한다 — 연금형+시작나이+월액이 다 확인되면 자산은 그대로 두고
추가로 IncomeStream을 만들어 시뮬레이션에 반영하고(정밀 모드), 아니면
지금처럼 비유동 자산으로만 남긴다(단순 모드, _apply_pension_followup_answer
참고).

사용자가 텍스트 대신 이미지(은행 앱 잔액 화면, 안심상속 조회 결과 캡처
등)를 올리면 extractor.extract_from_image()로 같은 체크리스트 흐름에
반영한다 — 텍스트 경로와 완전히 동일한 병합 로직(_merge_extraction)을
탄다. 화면이 흐릿하거나 판독 자체가 실패하면 추측해서 채우지 않고
다시 올리거나 말로 알려달라고 재질문한다.

다 모이면 이 에이전트 자신의 요약 응답과 함께, develop의 공유
schemas.FinancialProfile(flat 집계)로 눌러서 AgentOutput.financial_profile에
실어 보낸다 — 그 과정에서 정보가 어떻게 줄어드는지는 _to_shared_profile()
바로 위 docstring에 정리했다.
"""

from __future__ import annotations

import re
from typing import Any

from schemas import AgentInput, AgentName, AgentOutput, FinancialProfile, HandoffRequest

from . import extractor

#: handoff.py 규약 1번 — 이 에이전트의 상태 네임스페이스 키는 AgentName.value.
STATE_KEY = AgentName.ASSET_ORGANIZER.value

#: "기타"는 catch-all이라 콕 집어 되묻지 않는다 — 특정 유형 없이 뭉뚱그려
#: 말한 항목을 담는 그릇일 뿐, 빠짐을 확인할 대상이 아니다.
_ASSET_CATEGORIES: tuple[str, ...] = (
    "예금",
    "주식",
    "펀드",
    "부동산",
    "자동차",
    "퇴직연금",
)
#: tax_calculator 담당자가 확정해준 세법상 금융자산 분류 기준. 부동산은
#: real_estate_value로 이미 따로 담기므로 여기 없고, "기타"(자동차·퇴직연금
#: 포함)는 담당자가 항목명을 보고 자기 쪽에서 추가 확인하기로 했으므로
#: 여기서 금융자산으로 추측해 넣지 않는다 — _to_shared_profile() 참고.
_FINANCIAL_ASSET_TYPES: frozenset[str] = frozenset({"예금", "주식", "펀드"})
_LIABILITY_CATEGORY = "부채"
_INSURANCE_CATEGORY = "보험"
_ALL_CATEGORIES: tuple[str, ...] = (
    *_ASSET_CATEGORIES,
    _LIABILITY_CATEGORY,
    _INSURANCE_CATEGORY,
)

_OPENING_PROMPT = (
    "보유하고 계신 자산과 부채를 정리해드릴게요. "
    "예금·주식·펀드·부동산·보험 등 자산과 대출 등 부채를 편하게 말씀해주세요. "
    "은행 앱 화면이나 안심상속 조회 결과를 사진으로 올려주셔도 됩니다."
)

_IMAGE_UNREADABLE_REPLY = (
    "이미지가 잘 안 보이는데 다시 올려주시거나 말씀으로 알려주실 수 있을까요?"
)

#: 부채 정밀/단순 이중 모드와 완전히 같은 패턴(한 번만 묻고, 강제로 재질문
#: 안 함, current_age 기준 상대 표현 해석 재사용)으로 퇴직연금 수령 방식을
#: 확인한다 — _apply_pension_followup_answer() 참고.
_PENSION_FOLLOWUP_QUESTION = (
    "퇴직연금은 일시금으로 받으실 예정인가요, 아니면 연금으로 나눠 받으실 "
    "예정인가요? 연금으로 받으실 경우 언제부터·월 얼마씩 받으실지 아시면 "
    "같이 알려주세요. 모르셔도 괜찮아요."
)
_PENSION_ANNUITY_RE = re.compile(r"연금")

_NEGATIVE_ANSWER_RE = re.compile(r"없|아니")

# 부채 정밀 모드 후속질문 답변 해석용. "(?<!\d)...(?!\d)"로 앞뒤에 숫자가
# 더 없는 "독립된" 1~3자리 숫자만 잡는다 — 이게 없으면 "2030년까지"의
# "030"이 "030년"으로 걸려 상대 연수 3년으로 잘못 해석된다(실측 확인).
# 캘린더 연도 표현은 다루지 않는다 — 애매하면 추측하지 않고 단순 모드로.
_ABSOLUTE_AGE_RE = re.compile(r"(?<!\d)(\d{1,3})(?!\d)\s*(?:살|세)")
_RELATIVE_YEARS_RE = re.compile(r"(?<!\d)(\d{1,3})(?!\d)\s*년")


def _format_krw(amount: int) -> str:
    """money 표기 변환. retirement_planner/format_utils.py와 동일 로직의
    로컬 복제본이다 — 두 에이전트가 서로 import하지 않도록 각자 폴더에
    두기로 했다(레지스트리 방식에서 에이전트 패키지는 서로 독립이 원칙).
    포맷 규칙 자체를 고칠 일이 생기면 두 곳 다 함께 고칠 것."""
    negative = amount < 0
    amount = abs(amount)

    eok, rest = divmod(amount, 100_000_000)
    man = rest // 10_000

    if eok == 0 and man == 0:
        text = f"{amount:,}원"
    else:
        parts = []
        if eok:
            parts.append(f"{eok}억")
        if man:
            parts.append(f"{man:,}만원")
        text = " ".join(parts)

    return f"-{text}" if negative else text


# =================================================================== 상태


def _empty_state() -> dict[str, Any]:
    return {
        "assets": [],
        "liabilities": [],
        "insurance": [],
        "incomes": [],
        "checked_categories": [],
        "pending_categories": [],
        "pending_amounts": [],
        "liability_followup_asked": False,
        "pension_followup_asked": False,
        "pension_followup_resolved": False,
        "status": "collecting",
    }


def _load_state(context: dict[str, Any] | None) -> dict[str, Any]:
    namespaced = (context or {}).get(STATE_KEY, {})
    state = _empty_state()
    if isinstance(namespaced, dict):
        for key in state:
            if key in namespaced:
                state[key] = namespaced[key]
    return state


def _output(
    state: dict[str, Any],
    reply: str,
    *,
    financial_profile: FinancialProfile | None = None,
    handoffs: list[HandoffRequest] | None = None,
) -> AgentOutput:
    return AgentOutput(
        agent=AgentName.ASSET_ORGANIZER,
        reply=reply,
        next_action=None,
        handoffs=handoffs or [],
        financial_profile=financial_profile,
        data={STATE_KEY: state},
    )


def _mark_checked(state: dict[str, Any], category: str) -> None:
    if category not in state["checked_categories"]:
        state["checked_categories"].append(category)


def _add_pending_amount(state: dict[str, Any], item: dict[str, Any]) -> None:
    key = "asset_type" if item["kind"] == "asset_value" else "liability_type"
    already_pending = any(
        existing.get("kind") == item["kind"] and existing.get(key) == item.get(key)
        for existing in state["pending_amounts"]
    )
    if not already_pending:
        state["pending_amounts"].append(item)


def _drop_pending_amount(state: dict[str, Any], kind: str, type_value: str) -> None:
    key = "asset_type" if kind == "asset_value" else "liability_type"
    state["pending_amounts"] = [
        item
        for item in state["pending_amounts"]
        if not (item.get("kind") == kind and item.get(key) == type_value)
    ]


def _append_resolved_pending_item(
    state: dict[str, Any], item: dict[str, Any], amount: int
) -> None:
    if item["kind"] == "asset_value":
        state["assets"].append(
            {
                "type": item["asset_type"],
                "value": amount,
                "liquid": None,
                "return_rate": None,
            }
        )
    else:
        state["liabilities"].append(
            {
                "type": item["liability_type"],
                "remaining_balance": amount,
                "monthly_payment": None,
                "end_age": None,
                "note": None,
            }
        )


def _is_negative_answer(message: str) -> bool:
    return bool(_NEGATIVE_ANSWER_RE.search(message))


def _merge_extraction(
    state: dict[str, Any],
    asset_result: extractor.ExtractionResult,
    liabilities: list[Any],
    liability_missing: list[dict[str, Any]],
) -> bool:
    """extract_financial_slots()/extract_liabilities()(텍스트 경로)와
    extract_from_image()(이미지 경로) 양쪽이 만든 결과를 같은 방식으로
    state에 반영한다 — 두 입력 채널이 하나의 체크리스트 병합 로직을
    공유한다. 새 항목을 하나라도 반영했으면 True를 돌려준다(호출부가
    "없어요" 일괄 확정 여부를 판단할 때 씀).

    보험은 자산·부채와 달리 금액이 없어도(InsuranceTag.value=0,
    note="금액 미언급") 카테고리가 바로 확인된 것으로 처리한다 —
    extractor.py가 이미 그렇게 판단해서 넘겨준다(보험은 engine 계산에서
    제외되는 태그라 0이어도 안전하다는 원칙, extractor.py 참고)."""
    for asset in asset_result.assets:
        state["assets"].append(asset.model_dump(mode="json"))
        _mark_checked(state, asset.type)
        _drop_pending_amount(state, "asset_value", asset.type)

    for liability in liabilities:
        state["liabilities"].append(liability.model_dump(mode="json"))
        _mark_checked(state, _LIABILITY_CATEGORY)
        _drop_pending_amount(state, "liability_value", liability.type)

    for tag in asset_result.insurance_tags:
        state["insurance"].append(tag.model_dump(mode="json"))
        _mark_checked(state, _INSURANCE_CATEGORY)

    # kind=="asset_value"만 처리한다 — 나머지(예: "unclear")는 extractor.py의
    # _apply_llm_payload()가 LLM 원문을 화이트리스트 없이 그대로 담아 보낼 수
    # 있는 자유텍스트라, 여기서 의도적으로 건너뛰어 state/reply 어디에도
    # 노출시키지 않는다(이미지 PII 잔여 위험 조사 결과 — extractor.py의
    # 관련 주석 참고). 나중에 다른 kind를 처리하게 되면 그 reason 원문을
    # 그대로 노출하지 말 것.
    for item in asset_result.missing:
        if item.get("kind") == "asset_value":
            _mark_checked(state, item["asset_type"])
            _add_pending_amount(state, item)

    for item in liability_missing:
        _mark_checked(state, _LIABILITY_CATEGORY)
        _add_pending_amount(state, item)

    return bool(asset_result.assets or liabilities or asset_result.insurance_tags)


def _liabilities_needing_followup(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        liability
        for liability in state["liabilities"]
        if liability["monthly_payment"] is None or liability["end_age"] is None
    ]


def _liability_followup_question(state: dict[str, Any]) -> str:
    types = list(
        dict.fromkeys(
            liability["type"] for liability in _liabilities_needing_followup(state)
        )
    )
    types_text = ", ".join(types)
    return (
        f"혹시 {types_text}은(는) 월 얼마씩 갚고 계신지, 언제쯤 다 갚으실 예정인지도 "
        "아시면 알려주세요. 모르셔도 괜찮아요."
    )


def _parse_end_age(message: str, current_age: int | None) -> int | None:
    """current_age를 이미 아는 상태에서만 상대 표현을 해석한다 —
    extractor.py의 "문맥 없는 파싱에서는 추측하지 않는다" 원칙과 다른
    자리다 (여기는 이미 아는 값 기준 계산이지, 지어내는 게 아니다).
    current_age는 이제 이 에이전트가 직접 모으지 않고 develop의 공유
    financial_profile(payload.financial_profile.current_age)에서 온다 —
    retirement_planner가 먼저 물어봤어야 존재한다. 없으면 절대 표현만
    해석하고 상대 표현은 포기한다(추측하지 않음)."""
    absolute_match = _ABSOLUTE_AGE_RE.search(message)
    if absolute_match:
        age = int(absolute_match.group(1))
        if age > 130:
            return None
        if current_age is not None and age < current_age:
            return None
        return age

    if current_age is None:
        return None

    relative_match = _RELATIVE_YEARS_RE.search(message)
    if relative_match:
        years = int(relative_match.group(1))
        end_age = current_age + years
        if end_age <= 130:
            return end_age

    return None


def _apply_liability_followup_answer(
    state: dict[str, Any], message: str, current_age: int | None
) -> None:
    """후속질문 답변을 해석해 가장 먼저 대기 중인 부채 하나에만 반영한다
    (부채가 여러 개여도 뭉뚱그려 물어본 것이라 특정 부채를 가리키지 않는다).
    monthly_payment/end_age 둘 다 못 알아들었으면(예: "몰라요", "나중에요")
    아무것도 채우지 않는다 — 재질문하지 않고 단순 모드로 남긴다."""
    targets = _liabilities_needing_followup(state)
    if not targets:
        return
    target = targets[0]

    monthly_payment = extractor.parse_monthly_expense_answer(message)
    if monthly_payment is not None:
        target["monthly_payment"] = monthly_payment

    end_age = _parse_end_age(message, current_age)
    if end_age is not None:
        target["end_age"] = end_age


# ============================================================ 퇴직연금 소득 전환


def _has_pension_asset(state: dict[str, Any]) -> bool:
    return any(a["type"] == "퇴직연금" for a in state["assets"])


def _wants_pension_annuity(message: str) -> bool:
    return bool(_PENSION_ANNUITY_RE.search(message))


def _parse_pension_start_age(message: str, current_age: int | None) -> int | None:
    """퇴직연금 수령 시작 나이 파싱. 부채 정밀 모드의 _parse_end_age()와
    나이 표현 해석 로직이 완전히 같다(절대 "OO살/세" 우선, 없으면
    current_age 기준 상대 "N년" 변환, current_age 없으면 상대 표현 포기) —
    "종료 나이"든 "시작 나이"든 나이 표현 자체를 해석하는 로직은 동일해서
    새로 만들지 않고 그대로 재사용한다."""
    return _parse_end_age(message, current_age)


def _apply_pension_followup_answer(
    state: dict[str, Any], message: str, current_age: int | None
) -> None:
    """퇴직연금 수령 방식 후속질문 답변을 해석한다. 부채 정밀 모드와 같은
    원칙 — 연금형 의사 + 시작 나이 + 월 수령액이 전부 확인돼야 정밀 모드로
    보고 IncomeStream을 만든다. 하나라도 못 알아들었으면(일시금, "몰라요",
    무응답 등) 아무것도 만들지 않고 단순 모드(퇴직연금은 그대로 비유동
    자산으로만 유지)로 남긴다 — 재질문하지 않는다. 자산 목록 자체는 이
    함수가 건드리지 않으므로 정보 손실이 없다(_to_shared_profile 참고)."""
    state["pension_followup_resolved"] = True

    if not _wants_pension_annuity(message):
        return

    start_age = _parse_pension_start_age(message, current_age)
    monthly_amount = extractor.parse_monthly_expense_answer(message)
    if start_age is None or monthly_amount is None:
        return

    state["incomes"].append(
        {
            "type": "퇴직연금",
            "monthly": monthly_amount,
            "start_age": start_age,
            "end_age": None,  # 국민연금과 동일 기본값 — 종신, 종료 나이는 안 물어봄
        }
    )


def _format_summary(state: dict[str, Any]) -> str:
    lines = ["확정된 자산·부채 목록입니다."]

    assets = state["assets"]
    total_assets = sum(a["value"] for a in assets)
    if assets:
        lines.append("\n[자산]")
        lines.extend(f"- {a['type']}: {_format_krw(a['value'])}" for a in assets)
        lines.append(f"자산 합계: {_format_krw(total_assets)}")
    else:
        lines.append("\n[자산] 없음")

    liabilities = state["liabilities"]
    total_liabilities = sum(liability["remaining_balance"] for liability in liabilities)
    if liabilities:
        lines.append("\n[부채]")
        lines.extend(
            f"- {liability['type']}: {_format_krw(liability['remaining_balance'])}"
            for liability in liabilities
        )
        lines.append(f"부채 합계: {_format_krw(total_liabilities)}")
    else:
        lines.append("\n[부채] 없음")

    # 보험은 순자산 계산에 넣지 않는다 — 노후 재원 계산에서 제외되는
    # 태그라는 기존 원칙 그대로(engine.py가 이 값을 아예 보지 않음).
    insurance = state["insurance"]
    if insurance:
        lines.append("\n[보험]")
        lines.extend(
            f"- {tag['type']}: {_format_krw(tag['value'])}"
            + (f" ({tag['note']})" if tag.get("note") else "")
            for tag in insurance
        )
    else:
        lines.append("\n[보험] 없음")

    lines.append(f"\n순자산: {_format_krw(total_assets - total_liabilities)}")
    return "\n".join(lines)


# ============================================== 공유 financial_profile 변환


def _to_shared_profile(state: dict[str, Any]) -> FinancialProfile:
    """체크리스트 결과를 develop의 공유 FinancialProfile(flat 집계)로 눌러낸다.

    ⚠️ 정보 손실 지점 (요약 보고 참고, 스키마 확장 여부는 팀장 결정 사항):
    1. 자산 항목별 liquid(유동성 여부)·return_rate(수익률)가 사라진다 —
       flat 스키마는 유형별 "총액" 하나만 받는다. retirement_planner가
       예전처럼 부동산을 기본 비유동으로 계산하려면, 이 요약 값이 아니라
       extra["asset_organizer"]["assets"](아래)의 itemized 리스트를 다시
       읽어야 한다.
    2. 부채의 monthly_payment/end_age(정밀 모드 판단 기준)가 total_debts
       하나로 뭉개진다 — 마찬가지로 extra 를 봐야 정밀/단순 모드를 구분할
       수 있다. total_debts만 보는 소비자는 모든 부채를 "단순 모드"로
       오해할 수 있다.
    3. financial_assets는 tax_calculator 담당자가 확정해준 기준(예금·적금·
       주식·일반 펀드 → 금융자산, 부동산은 제외, 기타/자동차/퇴직연금 등은
       금융자산으로 분류하지 않고 other_assets에 남김)에 따라 _FINANCIAL_
       ASSET_TYPES에 속한 유형만 합산한다 — "기타"를 금융자산으로 볼지는
       tax_calculator 쪽에서 항목명을 보고 추가로 확인하기로 했으므로
       여기서 대신 판단하지 않는다. 유형별 배타적 분류라 financial_assets/
       other_assets/real_estate_value 세 필드는 서로 겹치지 않는다.
       (최대주주 보유주식 등 공제 제외 판단은 tax_calculator 책임 —
       "금융자산 분류 = 공제대상 확정"이 아니라고 명시함.)
    4. financial_debts는 아예 채우지 않는다 — Liability.type이 자유
       문자열이라 "금융기관 채무"인지 판단할 근거가 없다. tax_calculator가
       채권자 정보를 기준으로 직접 확인 질문을 넣기로 했다. total_debts
       (전체 채무 합계)에는 전부 들어간다.
    5. InsuranceTag(보험)는 flat 스키마에 대응 필드가 아예 없다 — 부채의
       monthly_payment/end_age(2번)와 같은 방식으로 extra["asset_organizer"]
       ["insurance"]에 원본 그대로 보존한다. flat 필드만 보는 소비자에게는
       여전히 안 보이지만, 최소한 조회는 가능하다.
    6. 퇴직연금을 연금형으로 받기로 확인되면(수령 방식 후속질문 참고)
       생기는 IncomeStream도 flat 스키마에 대응 필드가 없다 — insurance와
       같은 방식으로 extra["asset_organizer"]["incomes"]에 원본 그대로
       보존한다. retirement_planner가 이 리스트를 읽어 시뮬레이션에
       반영한다(assets에 남아 있는 퇴직연금 원금과는 이중 계산되지 않음 —
       liquid=False라 잔액 계산엔 애초에 원금이 안 들어가고 소득 흐름만
       추가되는 구조, adapter.py 참고).

    checked_categories에 있는 카테고리만 값을 채운다(전부는 아니어도
    최소 하나는 확인된 상태) — 아직 안 물어본 카테고리까지 0으로 채우면
    "확인 안 함"과 "확인했더니 0원"을 구분할 수 없게 된다. 이 함수는
    status=="done"(체크리스트 전부 완료) 시점에만 호출되므로 실제로는
    모든 카테고리가 checked_categories에 있다.
    """
    assets = state["assets"]
    liabilities = state["liabilities"]
    insurance = state["insurance"]

    real_estate_value = sum(a["value"] for a in assets if a["type"] == "부동산")
    # 3번 참고 — tax_calculator 담당자 확정 기준대로 예금/주식/펀드만
    # financial_assets로 분류한다. 부동산은 위에서 이미 분리했고, 그 외
    # (기타/자동차/퇴직연금 등)는 전부 other_assets로 남긴다 — 배타적
    # 분류라 세 필드가 겹치지 않는다.
    financial_assets = sum(
        a["value"] for a in assets if a["type"] in _FINANCIAL_ASSET_TYPES
    )
    other_assets = sum(
        a["value"]
        for a in assets
        if a["type"] != "부동산" and a["type"] not in _FINANCIAL_ASSET_TYPES
    )
    total_debts = sum(liability["remaining_balance"] for liability in liabilities)

    return FinancialProfile(
        real_estate_value=real_estate_value,
        financial_assets=financial_assets,
        other_assets=other_assets,
        total_debts=total_debts,
        extra={
            "asset_organizer": {
                "assets": assets,
                "liabilities": liabilities,
                "insurance": insurance,
                "incomes": state["incomes"],
            }
        },
    )


# ================================================================= 흐름


def _finalize(state: dict[str, Any]) -> AgentOutput:
    """체크리스트가 끝나면 develop 재작업 전 원래 의도("체크리스트 끝나면
    자연스럽게 시뮬레이션까지 이어짐")대로 retirement_planner에 핸드오프를
    건다. handoff.py 규약대로 AgentOutput.handoffs에 담으면(레거시
    next_action 문자열이 아니라) 오케스트레이터가 다음 턴을 Fast Path로
    바로 retirement_planner에 보낸다 — 실제로 실행해서 확인한 결과, 이
    신호가 없으면 사용자가 "은퇴"/"노후"/"연금" 같은 키워드를 새로 말하지
    않는 한 asset_organizer에 계속 머물러 있었다(체크리스트 완료 응답만
    반복)."""
    state["status"] = "done"
    return _output(
        state,
        _format_summary(state),
        financial_profile=_to_shared_profile(state),
        handoffs=[
            HandoffRequest(
                target=AgentName.RETIREMENT_PLANNER,
                reason="자산·부채 체크리스트 완료 — 은퇴자금 시뮬레이션으로 이어감",
            )
        ],
    )


def _continue_after_categories(
    payload: AgentInput, state: dict[str, Any]
) -> AgentOutput:
    if state["pending_amounts"]:
        item = state["pending_amounts"][0]
        label = item.get("asset_type") or item.get("liability_type")
        return _output(state, f"{label} 금액이 얼마인지 알려주시겠어요?")

    missing_categories = [
        category
        for category in _ALL_CATEGORIES
        if category not in state["checked_categories"]
    ]
    if missing_categories:
        state["pending_categories"] = missing_categories
        categories_text = ", ".join(missing_categories)
        return _output(
            state,
            f"아직 말씀 안 하신 항목이 있어요: {categories_text}. "
            "있으면 알려주시고, 없으면 '없음'이라고 답해주세요.",
        )

    if not state["liability_followup_asked"] and _liabilities_needing_followup(state):
        state["liability_followup_asked"] = True
        return _output(state, _liability_followup_question(state))

    if not state["pension_followup_asked"] and _has_pension_asset(state):
        state["pension_followup_asked"] = True
        return _output(state, _PENSION_FOLLOWUP_QUESTION)

    return _finalize(state)


def _handle_image_turn(payload: AgentInput, state: dict[str, Any]) -> AgentOutput:
    """이미지 한 장을 텍스트와 동일한 체크리스트 병합 로직으로 반영한다.
    판독 자체가 실패하면(흐릿함/형식 불명/API 실패) 추측해서 채우지 않고
    다시 올리거나 말로 알려달라고 재질문한다 — 이 턴에서는 카테고리
    상태를 아예 건드리지 않는다."""
    asset_result, liabilities, liability_missing = extractor.extract_from_image(
        payload.image_base64, payload.image_media_type or "image/jpeg"
    )
    if any(item.get("kind") == "image_unreadable" for item in asset_result.missing):
        return _output(state, _IMAGE_UNREADABLE_REPLY)

    _merge_extraction(state, asset_result, liabilities, liability_missing)
    state["pending_categories"] = []
    return _continue_after_categories(payload, state)


def _run_turn(payload: AgentInput, state: dict[str, Any]) -> AgentOutput:
    message = (payload.user_message or "").strip()
    has_image = bool(payload.image_base64)

    is_first_turn = not (
        state["assets"]
        or state["liabilities"]
        or state["insurance"]
        or state["checked_categories"]
        or state["pending_categories"]
        or state["pending_amounts"]
    )
    if is_first_turn and not message and not has_image:
        return _output(state, _OPENING_PROMPT)

    if has_image:
        return _handle_image_turn(payload, state)

    # 0) 부채 정밀 모드 후속질문에 대한 답이면 그것부터 처리한다. current_age는
    #    더 이상 이 에이전트가 직접 모으지 않고, develop의 공유
    #    financial_profile에서 온다(retirement_planner가 먼저 물어봤을 때만
    #    존재) — 없으면 절대 나이 표현만 해석하고 상대 표현은 포기한다.
    was_awaiting_liability_followup = state[
        "liability_followup_asked"
    ] and _liabilities_needing_followup(state)
    if was_awaiting_liability_followup:
        current_age = (
            payload.financial_profile.current_age
            if payload.financial_profile is not None
            else None
        )
        _apply_liability_followup_answer(state, message, current_age)
        return _continue_after_categories(payload, state)

    # 0-2) 퇴직연금 수령 방식 후속질문에 대한 답이면 그것부터 처리한다 —
    #      0)과 완전히 같은 이유로 current_age를 공유 financial_profile에서
    #      가져온다.
    was_awaiting_pension_followup = (
        state["pension_followup_asked"] and not state["pension_followup_resolved"]
    )
    if was_awaiting_pension_followup:
        current_age = (
            payload.financial_profile.current_age
            if payload.financial_profile is not None
            else None
        )
        _apply_pension_followup_answer(state, message, current_age)
        return _continue_after_categories(payload, state)

    had_pending_categories = bool(state["pending_categories"])
    resolved_via_bare_amount = False

    # 1) 대기 중이던 금액 질문에 대한 단답("5억이요" 등) 우선 처리 — 유형
    #    키워드 없이 숫자만 온 경우라 일반 추출로는 못 잡는다.
    if state["pending_amounts"]:
        bare_amount = extractor.parse_monthly_expense_answer(message)
        if bare_amount is not None:
            item = state["pending_amounts"].pop(0)
            _append_resolved_pending_item(state, item, bare_amount)
            resolved_via_bare_amount = True
        elif _is_negative_answer(message) and not re.search(r"\d", message):
            # "없어요"/"모르겠어요" — 그 항목은 '보유 안 함'으로 보고 대기에서 뺀다.
            # ("주식 없어요"처럼 유형 키워드가 섞여 있어도, 숫자가 없고 순수
            #  부정이면 되묻기 루프에 빠지지 않게 여기서 소비한다.)
            state["pending_amounts"].pop(0)
            resolved_via_bare_amount = True

    if not resolved_via_bare_amount:
        asset_result = extractor.extract_financial_slots(message)
        liabilities, liability_missing = extractor.extract_liabilities(message)
        found_new_items = _merge_extraction(
            state, asset_result, liabilities, liability_missing
        )

        # "없어요"처럼 순수 부정 답변일 때만 남은 대기 카테고리를 전부
        # 확정한다 — "아니요, 예금 3천 있어요"처럼 실제 항목이 섞여 있으면
        # 그 항목만 반영하고 나머지는 다음 라운드에 다시 되묻는다.
        if (
            had_pending_categories
            and not found_new_items
            and _is_negative_answer(message)
        ):
            for category in state["pending_categories"]:
                _mark_checked(state, category)

    state["pending_categories"] = []
    return _continue_after_categories(payload, state)


def run(payload: AgentInput) -> AgentOutput:
    state = _load_state(payload.context)
    return _run_turn(payload, state)
