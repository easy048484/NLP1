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

⚠️ 팀 계획서 확정(2026-08-31, retirement_planner 데모 제외 이후): 이
에이전트가 "상속재산(estate) 파악"을 전담한다 — 생전(본인 재산 목록화,
위 설명이 그대로 적용)과 사후(남은 가족이 안심상속 원스톱서비스 등에서
조회한 결과를 해석) 두 축 모두. 두 모드를 가르는 방식은 decedent_estate
의 intent 게이트(review/prepare, agents/decedent_estate/agent.py 참고)와
완전히 같은 패턴 — context 평면 키("mode": "pre_need"|"post_death")로
매 턴 override 가능한 세션 플래그이지, 발화 문맥으로 매 턴 추론하지
않는다(_resolve_mode 참고). 사후 모드에서는 "OO은행은 잔액까지 나왔고
OO증권은 계좌만 확인됐어요" 같은 다기관 조회 결과 문장을
extractor.extract_disclosures()로 먼저 해석하고, 실패/못 찾으면 조용히
버리지 않고 기존 일반 추출 경로로 폴백한다.

이와 함께 자산 금액에 3단계 신뢰도를 도입했다: confirmed(금액까지 확인,
기존 동작과 동일 기본값) / unknown_amount(존재는 확인, 금액은 영구적으로
모름 — 생전 모드에서 "몰라요"로 답했거나 사후 모드에서 기관이 존재만
확인해준 경우, 다시 캐묻지 않음) / 미확인(아직 언급 자체가 안 됨, 기존
체크리스트 로직 그대로). unknown_amount 자산은 순자산·flat 집계
어디에서도 조용히 0으로 잡히지 않고 총액에서 명시적으로 제외되며
(_format_summary/_to_shared_profile 참고), itemized 원본에는 confidence
가 그대로 남아 나중에 tax_calculator 등이 판단 근거로 쓸 수 있다. 이번
라운드는 재산 목록화에만 집중한다 — 세금 계산·배분 판단은 여전히 범위
밖이다.
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

#: 생전(본인 재산 목록화, 기존 기본 동작) / 사후(남은 가족이 안심상속
#: 원스톱서비스 등에서 조회한 결과 해석) 두 모드. decedent_estate의 intent
#: 게이트(review/prepare, agents/decedent_estate/agent.py._resolve_intent)와
#: 완전히 같은 패턴을 그대로 따른다 — 새 메커니즘을 발명하지 않았다:
#: context 최상위 평면 키("mode")로 매 턴 명시적으로 보낼 수 있고(이번 턴
#: 값이 저장된 상태보다 우선 — handoff.build_agent_context 원칙과 동일),
#: 미지정이면 조용히 기존 동작(pre_need)으로 기본 처리하며(하위 호환),
#: 값이 있는데 화이트리스트 밖이면 재질문한다. `schemas.AgentInput.axis`
#: (오케스트레이터가 "키워드 후보 0개" 폴백에만 쓰는 축)와는 의도적으로
#: 분리했다 — decedent_estate도 자기 axis(POST_DEATH 하나)와 별개로
#: intent를 자기 안에서 따로 관리한다, 같은 이유.
_PRE_NEED_MODE = "pre_need"
_POST_DEATH_MODE = "post_death"
_MODE_VALUES = (_PRE_NEED_MODE, _POST_DEATH_MODE)

_MODE_QUESTION = (
    "본인 재산을 정리하시는 건가요, 아니면 돌아가신 가족분의 재산을 정리하시는 "
    "건가요?"
)

_POST_DEATH_OPENING_PROMPT = (
    "돌아가신 가족분의 재산을 정리해드릴게요. 안심상속 원스톱서비스 등에서 "
    "조회하신 결과를 편하게 알려주세요 — 기관마다 확인되는 수준이 달라서, "
    '"OO은행은 잔액까지 나왔고 OO증권은 계좌만 확인됐어요" 처럼 아시는 만큼만 '
    "말씀해주셔도 됩니다. 은행 앱 화면이나 조회 결과를 사진으로 올려주셔도 됩니다."
)

_IMAGE_UNREADABLE_REPLY = (
    "이미지가 잘 안 보이는데 다시 올려주시거나 말씀으로 알려주실 수 있을까요?"
)

#: Round 12: 사후 모드 다기관 조회 해석(extract_disclosures)이 LLM 실패로
#: 일반 추출 경로(extract_financial_slots)에 폴백했는데, 그 일반 추출조차
#: 아무것도 구조화하지 못한 경우(found_new_items=False) 쓰는 명시적
#: 재질문. 이미지 판독 실패(_IMAGE_UNREADABLE_REPLY)와 완전히 같은 원칙 —
#: "이해 못했다"는 사실을 숨기지 않고, 다음 체크리스트 질문으로 조용히
#: 넘어가면서 사용자가 방금 한 답을 통째로 잃어버리는 일을 막는다.
_PARSE_FAILED_REPLY = (
    "말씀해주신 내용을 정확히 분류하지 못했어요. 어떤 자산·부채인지, 금액까지 "
    "확인되는지 아니면 존재만 확인되는지 다시 한번 말씀해주시겠어요?"
)
#: 일부는 구조화됐지만 나머지는 이해 못한 경우(부분 성공) — 이미 반영된
#: 항목은 그대로 두고, 다음 안내에 짧은 안내만 덧붙인다. 전체를 재질문
#: 상태로 되돌리면 이미 확인된 항목까지 다시 물어보는 것처럼 보여
#: 혼란스럽다.
_PARTIAL_UNRESOLVED_NOTE = (
    "\n\n(말씀 중 일부는 정확히 분류하지 못했어요 — 확인 안 된 부분이 있다면 "
    "다시 한번 말씀해주세요.)"
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
#: "없어요"(retract — 항목 자체가 없다는 뜻, 기존 동작)와 구분되는 "몰라요"
#: (존재는 있는데 금액을 모른다는 뜻) — 3단계 신뢰도의 "금액모름"으로
#: 영구 확정한다. _wants_unknown_amount() 참고.
_DONT_KNOW_AMOUNT_RE = re.compile(r"몰라|모르")

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
        "mode": None,
        "assets": [],
        "liabilities": [],
        "insurance": [],
        "incomes": [],
        "checked_categories": [],
        "pending_categories": [],
        "pending_amounts": [],
        "liability_followup_asked": False,
        "liability_followup_resolved": False,
        "pension_followup_asked": False,
        "pension_followup_resolved": False,
        "status": "collecting",
    }


def _load_state(context: dict[str, Any] | None) -> dict[str, Any]:
    context = context or {}
    namespaced = context.get(STATE_KEY, {})
    state = _empty_state()
    if isinstance(namespaced, dict):
        for key in state:
            if key in namespaced:
                state[key] = namespaced[key]

    # decedent_estate/state.py의 평면 키 폴백과 동일한 패턴 — 네임스페이스
    # (지난 턴 상태)가 기본이고, 이번 턴에 평면 키가 명시적으로 왔으면 그
    # 값이 우선한다("사용자가 이번 턴에 명시적으로 답한 값이 우선" 원칙,
    # handoff.build_agent_context와 동일). 빈 문자열은 "미지정"으로 보고
    # 무시한다 — 안 그러면 아직 선택 안 한 프론트가 mode=""를 보냈을 때
    # 이미 저장된 정상 값을 지워서 모드 게이트가 다시 열려버린다.
    flat_mode = context.get("mode")
    if flat_mode is not None and flat_mode != "":
        state["mode"] = flat_mode
    return state


def _resolve_mode(state: dict[str, Any]) -> tuple[str, bool]:
    """모드를 pre_need/post_death로 정리한다. decedent_estate._resolve_intent()
    와 완전히 같은 패턴 — 미지정(None)이면 조용히 기존 동작(pre_need)으로
    기본 처리하고(하위 호환 — mode를 모르는 기존 호출부도 그대로 생전
    체크리스트를 탄다), 값이 있는데 화이트리스트 밖이면 재질문 대상으로
    삼는다(두 번째 반환값 True). 잘못된 값 자체는 반환하지 않는다 — 호출부가
    재질문 여부만 보고 판단하면 된다."""
    mode = state.get("mode")
    if mode is None:
        return _PRE_NEED_MODE, False
    if mode not in _MODE_VALUES:
        return _PRE_NEED_MODE, True
    return mode, False


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
    state: dict[str, Any],
    item: dict[str, Any],
    amount: int,
    *,
    confidence: str = "confirmed",
) -> None:
    """confidence는 자산(asset_value)에만 의미가 있다 — 부채는 이번 라운드
    3단계 신뢰도 범위 밖이라(과제 경계, "이번 라운드는 재산 목록화에만
    집중") 항상 confirmed 취급 그대로 둔다."""
    if item["kind"] == "asset_value":
        state["assets"].append(
            {
                "type": item["asset_type"],
                "value": amount,
                "liquid": None,
                "return_rate": None,
                "confidence": confidence,
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


def _wants_unknown_amount(message: str) -> bool:
    return bool(_DONT_KNOW_AMOUNT_RE.search(message))


def _merge_extraction(
    state: dict[str, Any],
    asset_result: extractor.ExtractionResult,
    liabilities: list[Any],
    liability_missing: list[dict[str, Any]],
) -> tuple[bool, bool]:
    """extract_financial_slots()/extract_liabilities()(텍스트 경로)와
    extract_from_image()(이미지 경로) 양쪽이 만든 결과를 같은 방식으로
    state에 반영한다 — 두 입력 채널이 하나의 체크리스트 병합 로직을
    공유한다. (새 항목을 하나라도 반영했는지, 이해하지 못하고 남은 부분이
    있는지) 튜플을 돌려준다 — 호출부가 "없어요" 일괄 확정 여부, 그리고
    Round 12에서 발견된 "조용한 정보 유실"(구조화 실패를 성공처럼 넘기는
    것) 방어 여부를 판단할 때 쓴다.

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

    # kind=="asset_value"는 유형은 알지만 금액을 못 찾은 경우라 pending_amounts
    # 재질문으로 이어진다(정상 흐름, 정보 유실 아님). kind가 "unrecognized_segment"
    # (정규식·LLM 둘 다 유형 자체를 못 알아본 세그먼트)나 "unclear"(LLM이 스스로
    # "이해 못했다"고 표시한 부분)면 얘기가 다르다 — Round 11까지는 이 두 kind를
    # 그냥 건너뛰어서, 사용자가 뭔가 구체적으로 답했는데 결과적으로 아무 흔적도
    # 안 남는 "조용한 정보 유실"이 있었다(Round 12에서 실측 재현). 원문(reason)
    # 자체는 PII 잔여 위험이 있어 여전히 state/reply에 노출하지 않지만
    # (extractor.py의 관련 주석과 동일 원칙), "이해 못한 부분이 있었다"는
    # 신호는 has_unresolved_remainder로 남겨서 호출부가 조용히 다음 질문으로
    # 넘어가지 않고 명시적으로 재질문하도록 한다.
    has_unresolved_kind = False
    for item in asset_result.missing:
        kind = item.get("kind")
        if kind == "asset_value":
            _mark_checked(state, item["asset_type"])
            _add_pending_amount(state, item)
        elif kind == "asset_absent":
            # "예금은 없어요" — 그 유형은 확인 완료(없음)이지 금액 재질문
            # 대상이 아니다(extractor.py의 _SEGMENT_NEGATION_RE 참고).
            _mark_checked(state, item["asset_type"])
        elif kind in ("unrecognized_segment", "unclear"):
            has_unresolved_kind = True

    for item in liability_missing:
        _mark_checked(state, _LIABILITY_CATEGORY)
        if item.get("kind") != "liability_absent":
            # "대출은 없어요"(liability_absent)는 부채 카테고리 확인
            # 완료이지 금액 재질문 대상이 아니다 — asset_absent와 동일한
            # 이유(extractor.py의 _SEGMENT_NEGATION_RE 참고).
            _add_pending_amount(state, item)

    # ⚠️ 실측으로 발견된 오탐 지점: 자산 추출(_regex_extract)과 부채 추출
    # (extract_liabilities)은 같은 문장을 각자 독립적으로 세그먼트 분석한다
    # (자산 전용/부채 전용 키워드 사전을 따로 씀) — 그래서 "대출이 좀
    # 있어요"처럼 순수 부채 문장은 자산 추출기 입장에서는 "유형 자체를
    # 못 알아본 세그먼트"(unrecognized_segment)로 잡히지만, 실제로는 부채
    # 추출기가 이미 제대로 이해하고 있다(대출 유형 인식 + 금액 대기 또는
    # 확정). 이 경우까지 "이해 못함"으로 재질문하면 정상적으로 진행 중인
    # 부채 흐름을 방해하는 거짓 양성이 된다 — 부채 쪽에서 뭔가 신호가
    # 있었다면 자산 추출기의 unrecognized_segment/unclear는 무시한다.
    liability_extractor_understood = bool(liabilities or liability_missing)
    has_unresolved_remainder = (
        has_unresolved_kind and not liability_extractor_understood
    )

    found_new_items = bool(
        asset_result.assets or liabilities or asset_result.insurance_tags
    )
    return found_new_items, has_unresolved_remainder


def _merge_disclosures(
    state: dict[str, Any], items: list[extractor.DisclosureItem]
) -> bool:
    """사후 모드(extractor.extract_disclosures) 결과를 state에 반영한다.
    confidence=="unknown_amount"인 항목은 pending_amounts에 넣지 않고
    (다시 캐묻지 않음) 곧바로 자산 목록에 영구 확정으로 반영한다 —
    value=0은 실제 금액이 아니라 구조적 자리표시자일 뿐이며, 순자산
    계산은 반드시 confidence로 걸러서 써야 한다(_format_summary/
    _to_shared_profile 참고, models.Asset.confidence 필드 설명과 동일)."""
    for item in items:
        state["assets"].append(
            {
                "type": item.asset_type,
                "value": item.value if item.confidence == "confirmed" else 0,
                "liquid": None,
                "return_rate": None,
                "confidence": item.confidence,
            }
        )
        _mark_checked(state, item.asset_type)
        _drop_pending_amount(state, "asset_value", item.asset_type)
    return bool(items)


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
    아무것도 채우지 않는다 — 재질문하지 않고 단순 모드로 남긴다.

    ⚠️ 답을 받았으면(설령 "모름"이어도) 이 시점에 liability_followup_resolved를
    반드시 True로 마킹한다 — 실측으로 발견된 버그: 이 플래그 없이
    _liabilities_needing_followup(state)(부채 필드가 여전히 비어 있는지)만으로
    "아직 답변 대기 중인지"를 판단하면, 단순 모드로 확정된 뒤에도(필드가
    영구히 비어 있으므로) 그 조건이 계속 True로 남아 이후 모든 턴을 이
    함수가 계속 가로챈다 — 그 결과 뒤에 대기 중인 다른 후속질문(퇴직연금
    등)이 자기 차례를 영영 못 받는다. "재질문 금지" 원칙과 반대 방향
    문제라, 답을 받은 시점에 명확히 종결 처리하는 게 핵심이다."""
    state["liability_followup_resolved"] = True

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


def _is_confirmed(asset: dict[str, Any]) -> bool:
    """3단계 신뢰도 중 "confirmed"(금액까지 확인됨)인지. 기존(이번 라운드
    이전) 자산 dict는 confidence 키 자체가 없을 수 있어 기본값을
    "confirmed"로 둔다 — models.Asset.confidence의 기본값과 동일하게
    맞춰 하위 호환을 유지한다."""
    return asset.get("confidence", "confirmed") == "confirmed"


def _format_summary(state: dict[str, Any]) -> str:
    lines = ["확정된 자산·부채 목록입니다."]

    assets = state["assets"]
    confirmed_assets = [a for a in assets if _is_confirmed(a)]
    unknown_amount_assets = [a for a in assets if not _is_confirmed(a)]
    # 순자산 총액에 "금액모름" 항목을 조용히 0으로 넣지 않는다 — tax_calculator
    # 때 확정한 "미확인은 0원이 아니다" 원칙과 동일. 대신 목록에는 표시하고
    # 총액에서 빠졌다는 걸 명시적으로 안내한다(아래).
    total_assets = sum(a["value"] for a in confirmed_assets)
    if assets:
        lines.append("\n[자산]")
        lines.extend(
            f"- {a['type']}: {_format_krw(a['value'])}" for a in confirmed_assets
        )
        lines.extend(f"- {a['type']}: 금액 확인 안 됨" for a in unknown_amount_assets)
        # 앞의 마지막 불릿과 빈 줄 없이 붙으면 마크다운이 이 줄을 직전 항목의
        # 연속 문단으로 보고 한 줄에 이어 붙여 렌더링한다("- 주식: 금액 확인
        # 안 됨 자산 합계: ..."처럼 시각적으로 뭉쳐짐, 실측 확인) — 목록 종료를
        # 명확히 하려고 앞에 빈 줄을 넣는다(위 "\n[자산]"과 같은 관례).
        lines.append(f"\n자산 합계: {_format_krw(total_assets)}")
        if unknown_amount_assets:
            lines.append(
                f"({len(unknown_amount_assets)}개 항목은 금액이 확인되지 않아 "
                "총액에서 제외됨)"
            )
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
        lines.append(f"\n부채 합계: {_format_krw(total_liabilities)}")
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
    7. confidence=="unknown_amount"(3단계 신뢰도 — 사후 모드에서 기관이
       존재만 확인해준 경우, 또는 생전 모드에서 "몰라요"로 답한 경우)인
       자산은 real_estate_value/financial_assets/other_assets 세 필드
       어디에도 안 들어간다 — 확인 안 된 금액을 0으로 넣으면 순자산이
       실제보다 적어 보이게 왜곡된다(3번과 같은 원칙). extra의 itemized
       assets에는 confidence 그대로 남아 있으니, 정확한 총액이 필요한
       소비자는 flat 필드만 보지 말고 그걸 직접 걸러서 써야 한다.

    checked_categories에 있는 카테고리만 값을 채운다(전부는 아니어도
    최소 하나는 확인된 상태) — 아직 안 물어본 카테고리까지 0으로 채우면
    "확인 안 함"과 "확인했더니 0원"을 구분할 수 없게 된다. 이 함수는
    status=="done"(체크리스트 전부 완료) 시점에만 호출되므로 실제로는
    모든 카테고리가 checked_categories에 있다.
    """
    assets = state["assets"]
    liabilities = state["liabilities"]
    insurance = state["insurance"]

    # 7번 참고 — "금액모름" 자산(confidence != "confirmed")은 flat 집계
    # 세 필드(real_estate_value/financial_assets/other_assets) 어디에도
    # 안 들어간다. value=0이 구조적 자리표시자일 뿐이라 그대로 더하면
    # "확인 안 함"과 "확인했더니 0원"이 섞여 순자산이 실제보다 적어 보이는
    # 왜곡이 생긴다 — 3번과 같은 이유(추측 분류 금지)의 연장. itemized
    # 원본(아래 extra)에는 confidence 그대로 담아 보존한다.
    confirmed_assets = [a for a in assets if _is_confirmed(a)]

    real_estate_value = sum(
        a["value"] for a in confirmed_assets if a["type"] == "부동산"
    )
    # 3번 참고 — tax_calculator 담당자 확정 기준대로 예금/주식/펀드만
    # financial_assets로 분류한다. 부동산은 위에서 이미 분리했고, 그 외
    # (기타/자동차/퇴직연금 등)는 전부 other_assets로 남긴다 — 배타적
    # 분류라 세 필드가 겹치지 않는다.
    financial_assets = sum(
        a["value"] for a in confirmed_assets if a["type"] in _FINANCIAL_ASSET_TYPES
    )
    other_assets = sum(
        a["value"]
        for a in confirmed_assets
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
    """체크리스트가 끝나면 자산·부채 목록 + 순자산 요약만 보여주고 거기서
    끝난다.

    ⚠️ retirement_planner 핸드오프는 2026-08-30 데모 제외 결정으로
    비활성화했다(retirement_planner/spec.py의 keywords=[]와 같은 결정 —
    거기서 "사용자가 먼저 말 걸어서 도달"은 막았지만, 이 핸드오프
    (Fast Path)는 keywords와 무관해서 실제로 실행해보면 여전히 살아
    있었다). 원래는 develop 재작업 전 의도("체크리스트 끝나면 자연스럽게
    시뮬레이션까지 이어짐")대로 handoff.py 규약(AgentOutput.handoffs)에
    담아 오케스트레이터가 다음 턴을 Fast Path로 retirement_planner에
    보내게 했었다 — TODO: retirement_planner가 데모 범위에 다시 들어오면
    아래 handoffs= 줄의 주석을 풀어서 복원할 것(엔진 자체는 계속
    보존돼 있으므로 복원 자체는 이 줄만 되살리면 된다)."""
    state["status"] = "done"
    return _output(
        state,
        _format_summary(state),
        financial_profile=_to_shared_profile(state),
        # handoffs=[
        #     HandoffRequest(
        #         target=AgentName.RETIREMENT_PLANNER,
        #         reason="자산·부채 체크리스트 완료 — 은퇴자금 시뮬레이션으로 이어감",
        #     )
        # ],
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

    # -1) 생전/사후 모드 게이트 — decedent_estate의 will_type/intent 게이트와
    #     완전히 같은 위치(가장 먼저)·같은 방식(잘못된 값만 재질문)이다.
    mode, mode_invalid = _resolve_mode(state)
    if mode_invalid:
        state["mode"] = None  # 잘못된 값은 저장하지 않는다 — 다음 턴에 또 재질문
        return _output(state, _MODE_QUESTION)
    state["mode"] = mode

    is_first_turn = not (
        state["assets"]
        or state["liabilities"]
        or state["insurance"]
        or state["checked_categories"]
        or state["pending_categories"]
        or state["pending_amounts"]
    )
    if is_first_turn and not message and not has_image:
        opening = (
            _POST_DEATH_OPENING_PROMPT if mode == _POST_DEATH_MODE else _OPENING_PROMPT
        )
        return _output(state, opening)

    if has_image:
        return _handle_image_turn(payload, state)

    # 0) 부채 정밀 모드 후속질문에 대한 답이면 그것부터 처리한다. current_age는
    #    더 이상 이 에이전트가 직접 모으지 않고, develop의 공유
    #    financial_profile에서 온다(retirement_planner가 먼저 물어봤을 때만
    #    존재) — 없으면 절대 나이 표현만 해석하고 상대 표현은 포기한다.
    #    ⚠️ "아직 답변을 못 받았는지"는 _liabilities_needing_followup(state)
    #    (필드가 비어 있는지)가 아니라 liability_followup_resolved로 판단한다
    #    — 단순 모드로 확정돼도 필드는 영구히 비어 있으므로, 필드 상태만
    #    보면 이후 모든 턴에서 계속 "아직 답변 대기 중"으로 오판해 다른
    #    후속질문(퇴직연금 등)의 차례를 영영 못 오게 만드는 버그가 있었다.
    was_awaiting_liability_followup = (
        state["liability_followup_asked"] and not state["liability_followup_resolved"]
    )
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
    found_new_items = False
    has_unresolved_remainder = False

    # 1) 대기 중이던 금액 질문에 대한 단답("5억이요" 등) 우선 처리 — 유형
    #    키워드 없이 숫자만 온 경우라 일반 추출로는 못 잡는다.
    if state["pending_amounts"]:
        bare_amount = extractor.parse_monthly_expense_answer(message)
        if bare_amount is not None:
            item = state["pending_amounts"].pop(0)
            _append_resolved_pending_item(state, item, bare_amount)
            resolved_via_bare_amount = True
        elif _is_negative_answer(message) and not re.search(r"\d", message):
            # "없어요" — 그 항목 자체를 정정("사실은 없다")으로 보고
            # 대기에서 뺀다(자산 기록 자체를 안 만듦). "주식 없어요"처럼
            # 유형 키워드가 섞여 있어도, 숫자가 없고 순수 부정이면 되묻기
            # 루프에 빠지지 않게 여기서 소비한다.
            state["pending_amounts"].pop(0)
            resolved_via_bare_amount = True
        elif _wants_unknown_amount(message):
            # "몰라요"/"모르겠어요" — "없어요"(정정)와 다르게, 존재는
            # 확인됐지만 금액을 모른다는 뜻이다. 3단계 신뢰도의
            # "금액모름"으로 영구 확정하고 다시 캐묻지 않는다(부채/퇴직연금
            # 후속질문의 "한 번만 묻고 종결" 원칙과 동일 — 여기선 애초에
            # 물어봐도 답이 안 나올 걸 아는 경우라 더더욱 재질문 의미 없음).
            item = state["pending_amounts"].pop(0)
            _append_resolved_pending_item(state, item, 0, confidence="unknown_amount")
            resolved_via_bare_amount = True

    if not resolved_via_bare_amount:
        # 사후 모드는 여러 기관의 조회 결과 해석을 먼저 시도한다 — 정규식
        # 만으로는 부족할 가능성이 높아 LLM 폴백 경로(extractor.py의
        # extract_disclosures)를 재사용한다. None(LLM 사용 불가/호출 실패)
        # 이거나 빈 리스트(성공했지만 이 문장에서 못 찾음)면 조용히 버리지
        # 않고 기존 일반 추출 경로로 폴백한다 — "애매하면 안전한 쪽"
        # 원칙을 완전 실패시가 아니라 여기서도 지킨다.
        disclosures = (
            extractor.extract_disclosures(message) if mode == _POST_DEATH_MODE else None
        )
        liabilities, liability_missing = extractor.extract_liabilities(message)

        if disclosures:
            found_new_items = _merge_disclosures(state, disclosures)
            # 부채는 이 전용 파서 범위 밖이라(과제 경계) 같은 문장에 섞여
            # 있을 수 있는 부채 언급은 기존 정규식 경로로 별도 처리한다 —
            # 자산 파트는 이미 반영했으므로 빈 ExtractionResult를 넘긴다.
            # ⚠️ extract_disclosures()의 응답 스키마 자체에는 "일부 기관은
            # 이해 못했다"는 신호가 없다(문장을 세그먼트로 쪼개 대조하는
            # 별도 시스템 없이는 감지 불가 — Round 12에서 범용 segmentation은
            # 만들지 않기로 결정, "남은 한계"로 보고) — 그래서 이 분기는
            # has_unresolved_remainder를 세우지 않는다.
            liability_found_new, _ = _merge_extraction(
                state,
                extractor.ExtractionResult(status="ok"),
                liabilities,
                liability_missing,
            )
            found_new_items = liability_found_new or found_new_items
        else:
            # 사후 모드에서 다기관 해석이 실패/미시도(disclosures가 None 또는
            # 빈 리스트)했거나 애초에 생전 모드였던 경우 — 기존 일반 추출
            # 경로로 폴백한다. 이 경로는 has_unresolved_remainder 신호를
            # 실제로 채울 수 있다(_merge_extraction 참고) — Round 12에서
            # 고친 지점이 바로 여기다: 이 폴백조차 아무것도 못 건지면
            # 아래에서 조용히 넘어가지 않고 명시적으로 재질문한다.
            asset_result = extractor.extract_financial_slots(message)
            found_new_items, has_unresolved_remainder = _merge_extraction(
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
            # 명확한 부정 답변("없어요")은 "이해 못함"이 아니라 확정된 정정
            # 답변이다 — 재질문 대상에서 뺀다.
            has_unresolved_remainder = False

        # 조용한 실패 금지(Round 12): 이번 턴에 아무 항목도 새로 못 건졌고
        # (found_new_items=False) 그렇다고 명확한 부정 답변도 아니라면,
        # 사용자가 구체적으로 뭔가 답했는데 정규식·LLM 둘 다 통째로 이해
        # 못했다는 뜻이다. 이 상태로 그냥 다음 체크리스트 질문(또는 전체
        # 카테고리 재나열)으로 넘어가면, 사용자 입장에서는 방금 한 답이
        # 그냥 무시된 것처럼 보인다 — 실제로 상태 어디에도 안 남기 때문에
        # "무시된 것처럼 보인다"가 아니라 정말로 무시된 것이다. 성공한
        # 것처럼 넘어가지 않고 실패를 명시적으로 알린다.
        if not found_new_items and has_unresolved_remainder:
            state["pending_categories"] = []
            return _output(state, _PARSE_FAILED_REPLY)

    state["pending_categories"] = []
    output = _continue_after_categories(payload, state)
    if has_unresolved_remainder and found_new_items:
        # 부분 성공: 이해한 항목은 그대로 반영해 정상 진행하되, 놓친 부분이
        # 있었다는 사실은 숨기지 않고 짧게 덧붙인다(항목별로 어떤 부분을
        # 놓쳤는지는 PII 위험 때문에 밝히지 않는다 — _merge_extraction 참고).
        output.reply = f"{output.reply}{_PARTIAL_UNRESOLVED_NOTE}"
    return output


def run(payload: AgentInput) -> AgentOutput:
    state = _load_state(payload.context)
    return _run_turn(payload, state)
