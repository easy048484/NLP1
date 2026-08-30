"""
은퇴자금 설계(retirement_gap) 에이전트 — 시뮬레이션 흐름 담당.

⚠️ develop 기준 재작업 메모: engine.py/engine_models.py/adapter.py/
format_utils.py는 예전 asset_organizer 세션들에서 이미 검증된 계산
로직을 그대로 옮겨온 것이다(한 줄도 바꾸지 않음). 이 파일(agent.py)만
새로 짰다 — 자산·부채 "체크리스트"는 이제 agents/asset_organizer/가
전담하고, 여기서는 시뮬레이션에 필요한 최소 슬롯(현재 나이, 월 생활비)만
확인한 뒤 바로 계산한다.

develop의 공유 schemas.FinancialProfile(flat 집계)에서 두 가지를 읽는다:
1. current_age/monthly_expense — 이미 다른 턴/다른 에이전트가 물어봤으면
   재질문하지 않고 그대로 쓴다 (공유 프로필의 존재 이유 그대로).
2. extra["asset_organizer"] — asset_organizer가 이미 자산·부채 체크리스트를
   끝냈다면, 거기 담긴 itemized 리스트(유동성·정밀/단순 부채 모드 정보
   포함)를 그대로 엔진 입력으로 쓴다. 없으면(사용자가 이 에이전트에게
   바로 말을 건 경우) real_estate_value/financial_assets/other_assets/
   total_debts 같은 flat 합계만으로 단순화된 자산·부채 1건씩을 합성한다
   (부동산은 이때도 기본 비유동 처리 — _synthesize_assets_from_flat 참고).
   같은 extra 안의 "incomes"는 퇴직연금을 연금형으로 받기로 확인됐을
   때만 asset_organizer가 채워두는 소득 흐름이다 — flat 집계엔 대응
   필드가 없어 itemized 데이터가 없으면 합성할 방법도 없으므로 그냥
   빈 목록으로 둔다(_build_engine_input 참고).
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from schemas import AgentInput, AgentName, AgentOutput
from schemas import FinancialProfile as SharedProfile

from . import models
from .adapter import to_engine_profile
from .engine import SimulationResult, simulate_scenarios
from .format_utils import format_krw

#: handoff.py 규약 1번 — 이 에이전트의 상태 네임스페이스 키는 AgentName.value.
STATE_KEY = AgentName.RETIREMENT_PLANNER.value

_OPENING_PROMPT = (
    "은퇴 후 자금이 충분할지 시뮬레이션해드릴게요. "
    "현재 나이와 예상 월 생활비를 알려주세요."
)

_AGE_RE = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")
_UNIT_MULTIPLIERS: dict[str, int] = {
    "조": 1_000_000_000_000,
    "억": 100_000_000,
    "천만": 10_000_000,
    "백만": 1_000_000,
    "천": 10_000_000,  # asset_organizer/extractor.py와 동일한 관례 — "3천"=3천만원
    "만": 10_000,
    "원": 1,
}
_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(조|억|천만|백만|천|만|원)")
_NOISE_RE = re.compile(r"정도|쯤|가량|약|한(?=\s*\d)")


def _parse_amount(text: str) -> int | None:
    """asset_organizer/extractor.py의 _parse_amount와 같은 로직의 로컬
    복제본이다 — 두 에이전트가 서로 import하지 않도록 각자 폴더에 둔다
    (레지스트리 방식에서 에이전트 패키지는 서로 독립이 원칙). 금액 단위
    처리 규칙을 고칠 일이 생기면 두 곳 다 함께 고칠 것."""
    cleaned = _NOISE_RE.sub("", text)
    matches = _UNIT_RE.findall(cleaned)
    if not matches:
        return None
    total = Decimal("0")
    for number, unit in matches:
        total += Decimal(number) * _UNIT_MULTIPLIERS[unit]
    return int(total)


def _parse_age(text: str) -> int | None:
    match = _AGE_RE.search(text)
    if not match:
        return None
    age = int(match.group(1))
    return age if 0 <= age <= 130 else None


# =================================================================== 상태


def _empty_state() -> dict[str, Any]:
    return {
        "current_age": None,
        "monthly_expense": None,
        "pending_profile_field": None,
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


def _adopt_shared_profile(state: dict[str, Any], shared: SharedProfile | None) -> None:
    """이미 다른 턴/다른 에이전트가 확인해둔 값이 있으면 재질문하지 않고
    그대로 받아들인다 — 공유 financial_profile을 두는 이유 그 자체."""
    if shared is None:
        return
    if state["current_age"] is None and shared.current_age is not None:
        state["current_age"] = shared.current_age
    if state["monthly_expense"] is None and shared.monthly_expense is not None:
        state["monthly_expense"] = shared.monthly_expense


def _output(
    state: dict[str, Any],
    reply: str,
    *,
    financial_profile: SharedProfile | None = None,
) -> AgentOutput:
    return AgentOutput(
        agent=AgentName.RETIREMENT_PLANNER,
        reply=reply,
        next_action=None,
        financial_profile=financial_profile,
        data={STATE_KEY: state},
    )


def _own_profile_update(state: dict[str, Any]) -> SharedProfile:
    """확정된 슬롯만 실어 보낸다 — 아직 모르는 필드는 None으로 두어
    merged_with()가 세션의 기존 값을 덮어쓰지 않게 한다."""
    return SharedProfile(
        current_age=state["current_age"], monthly_expense=state["monthly_expense"]
    )


# ================================================== flat 프로필 → 엔진 입력


def _synthesize_assets_from_flat(shared: SharedProfile) -> list[models.Asset]:
    """asset_organizer의 itemized 데이터가 없을 때(예: 사용자가 이 에이전트
    에게 바로 말을 건 경우) flat 합계만으로 단순화된 자산 목록을 만든다.
    부동산은 여전히 기본 비유동으로 취급된다(adapter.py가 type="부동산"
    이면 자동으로 처리) — 유형별 세부 항목(예금 vs 주식 vs 펀드)은
    financial_assets 하나로 뭉쳐 있어 구분할 수 없으므로 "기타"로 합성한다
    (수익률 등 항목별 속성도 이 시점엔 이미 사라진 뒤라 복원 불가)."""
    assets: list[models.Asset] = []
    if shared.real_estate_value:
        assets.append(models.Asset(type="부동산", value=shared.real_estate_value))
    if shared.financial_assets:
        assets.append(models.Asset(type="기타", value=shared.financial_assets))
    if shared.other_assets:
        assets.append(models.Asset(type="기타", value=shared.other_assets))
    return assets


def _synthesize_liabilities_from_flat(shared: SharedProfile) -> list[models.Liability]:
    """total_debts 하나로만 있으면 정밀/단순 모드를 구분할 근거가 없어
    무조건 단순 모드(remaining_balance만 있고 monthly_payment/end_age는
    None)로 합성한다."""
    if not shared.total_debts:
        return []
    return [models.Liability(type="기타", remaining_balance=shared.total_debts)]


def _build_engine_input(state: dict[str, Any], shared: SharedProfile | None):
    extra_asset_organizer = (
        shared.extra.get("asset_organizer") if shared else None
    ) or {}
    raw_assets = extra_asset_organizer.get("assets")
    raw_liabilities = extra_asset_organizer.get("liabilities")
    raw_incomes = extra_asset_organizer.get("incomes")

    if raw_assets is not None:
        assets = [models.Asset(**a) for a in raw_assets]
    elif shared is not None:
        assets = _synthesize_assets_from_flat(shared)
    else:
        assets = []

    if raw_liabilities is not None:
        liabilities = [models.Liability(**liability) for liability in raw_liabilities]
    elif shared is not None:
        liabilities = _synthesize_liabilities_from_flat(shared)
    else:
        liabilities = []

    # flat 집계엔 소득 정보를 담을 자리가 없어 itemized 데이터가 없을 때
    # 합성할 방법이 없다 — 없으면 그냥 빈 목록(퇴직연금을 연금형으로
    # 받기로 확인된 적이 없다는 뜻이라 소득 흐름 자체가 없는 게 맞다).
    incomes = (
        [models.IncomeStream(**income) for income in raw_incomes]
        if raw_incomes is not None
        else []
    )

    return models.FinancialProfile(
        current_age=state["current_age"],
        monthly_expense=state["monthly_expense"],
        assets=assets,
        liabilities=liabilities,
        incomes=incomes,
    )


def _format_scenario(result: SimulationResult) -> str:
    if result.depletion_age is not None:
        status = f"{result.depletion_age}세에 자금이 고갈될 것으로 예상됩니다."
    else:
        status = "목표 나이까지 자금 고갈 없이 유지될 것으로 예상됩니다."
    remaining = format_krw(result.remaining_at_target)
    return f"- {result.target_age}세 기준: {status} (예상 잔액 {remaining})"


# ================================================================= 흐름


def _finalize(state: dict[str, Any], shared: SharedProfile | None) -> AgentOutput:
    profile = _build_engine_input(state, shared)
    engine_profile = to_engine_profile(profile)
    results = simulate_scenarios(engine_profile)

    state["status"] = "done"

    reply = "\n".join(
        [
            "오늘 돈 가치 기준 노후 자금 시뮬레이션 결과입니다.",
            *(_format_scenario(r) for r in results),
        ]
    )
    return _output(state, reply, financial_profile=_own_profile_update(state))


def _continue(state: dict[str, Any], shared: SharedProfile | None) -> AgentOutput:
    if state["current_age"] is None:
        state["pending_profile_field"] = "current_age"
        return _output(
            state,
            "현재 나이가 어떻게 되세요?",
            financial_profile=_own_profile_update(state),
        )

    if state["monthly_expense"] is None:
        state["pending_profile_field"] = "monthly_expense"
        return _output(
            state,
            "예상 월 생활비는 얼마인가요?",
            financial_profile=_own_profile_update(state),
        )

    state["pending_profile_field"] = None
    return _finalize(state, shared)


def _run_turn(payload: AgentInput, state: dict[str, Any]) -> AgentOutput:
    message = (payload.user_message or "").strip()
    _adopt_shared_profile(state, payload.financial_profile)

    is_first_turn = state["current_age"] is None and state["monthly_expense"] is None
    if is_first_turn and not message:
        return _output(state, _OPENING_PROMPT)

    if state["pending_profile_field"] == "current_age":
        age = _parse_age(message)
        if age is not None:
            state["current_age"] = age
            state["pending_profile_field"] = None
        return _continue(state, payload.financial_profile)

    if state["pending_profile_field"] == "monthly_expense":
        amount = _parse_amount(message)
        if amount is not None:
            state["monthly_expense"] = amount
            state["pending_profile_field"] = None
        return _continue(state, payload.financial_profile)

    return _continue(state, payload.financial_profile)


def run(payload: AgentInput) -> AgentOutput:
    state = _load_state(payload.context)
    return _run_turn(payload, state)
