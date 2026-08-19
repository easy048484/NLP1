"""대화 슬롯 상태.

세션 저장소(지원님 담당)가 아직 없으므로, 상태는 AgentInput.context와
AgentOutput.data를 통해 왕복시킵니다. schemas/agent_io.py를 건드리지 않고도
멀티턴이 되고, 나중에 서버 세션이 생기면 load/dump만 갈아끼우면 됩니다.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .procedure import StepId

#: context/data 안에서 이 에이전트가 쓰는 네임스페이스 키
STATE_KEY = "heir_navigator"

TriState = Literal["yes", "no", "unknown"]
AgreementStatus = Literal["none", "in_progress", "done", "conflict"]


class HeirState(BaseModel):
    """이 에이전트가 직접 물어서 채워야 하는 정보들."""

    #: 사망일(상속개시일). 모든 기한 계산의 기준점.
    death_date: Optional[date] = None
    #: 상속개시 있음을 안 날. 한정승인·상속포기 3개월의 진짜 기산점(민법 1019조).
    #: 보통 사망일과 같지만 다를 수 있어서 분리해둡니다.
    known_date: Optional[date] = None
    #: 이미 끝낸 단계
    completed: set[StepId] = Field(default_factory=set)
    #: 상속재산에 채무가 포함되는지. 한정승인/상속포기 분기의 핵심 변수.
    has_debt: TriState = "unknown"
    #: 유언장 존재 여부. yes/no가 확정되면 정호 에이전트로 넘깁니다.
    will_exists: TriState = "unknown"
    #: 공동상속인 간 협의 진행 여부
    agreement: AgreementStatus = "none"
    #: 이미 물어본 슬롯 이름. 같은 질문 반복 방지용.
    asked: set[str] = Field(default_factory=set)
    #: 대화 턴 수 (질문 페이스 조절용)
    turns: int = 0

    @field_validator("completed", "asked", mode="before")
    @classmethod
    def _coerce_set(cls, value: Any) -> Any:
        # JSON 왕복 시 set이 list로 내려오므로 되살립니다.
        if isinstance(value, (list, tuple)):
            return set(value)
        return value

    @property
    def effective_known_date(self) -> Optional[date]:
        return self.known_date or self.death_date

    def blocking_slot(self) -> Optional[str]:
        """이게 없으면 안내를 아예 만들 수 없는 슬롯.

        사망일 하나뿐입니다. 나머지는 안내를 먼저 드린 뒤 뒤에 붙여 묻습니다.
        질문 세 개를 연달아 던지고 아무 정보도 주지 않으면, 경황 없는 사용자가
        그 자리에서 이탈합니다.
        """
        return "death_date" if self.death_date is None else None

    def missing_required(self) -> list[str]:
        """알면 안내가 더 정확해지는 슬롯 (우선순위 순)."""
        missing: list[str] = []
        if self.death_date is None:
            missing.append("death_date")
        if not self.completed:
            missing.append("progress")
        if self.has_debt == "unknown" and StepId.ASSET_SEARCH in self.completed:
            # 재산조회를 마쳤는데도 채무 여부를 모르면 그때 묻습니다.
            # 조회 전에 물으면 사용자가 답할 수 없습니다.
            missing.append("has_debt")
        if self.will_exists == "unknown" and self.death_date is not None:
            missing.append("will_exists")
        if self.agreement == "none" and StepId.ACCEPT_DECIDE in self.completed:
            missing.append("agreement")
        return [slot for slot in missing if slot not in self.asked]

    def merge(self, other: "SlotUpdate") -> "HeirState":
        """추출된 슬롯을 덮어씁니다. None/unknown은 기존 값을 지우지 않습니다."""
        data = self.model_dump()
        if other.death_date is not None:
            data["death_date"] = other.death_date
        if other.known_date is not None:
            data["known_date"] = other.known_date
        if other.has_debt and other.has_debt != "unknown":
            data["has_debt"] = other.has_debt
        if other.will_exists and other.will_exists != "unknown":
            data["will_exists"] = other.will_exists
        if other.agreement and other.agreement != "none":
            data["agreement"] = other.agreement
        if other.completed_steps:
            data["completed"] = set(data["completed"]) | set(other.completed_steps)
        return HeirState.model_validate(data)


class SlotUpdate(BaseModel):
    """한 턴의 발화에서 뽑아낸 값들. 언급되지 않은 건 전부 None."""

    death_date: Optional[date] = None
    known_date: Optional[date] = None
    completed_steps: list[StepId] = Field(default_factory=list)
    has_debt: Optional[TriState] = None
    will_exists: Optional[TriState] = None
    agreement: Optional[AgreementStatus] = None

    @field_validator("death_date", "known_date", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("completed_steps", mode="before")
    @classmethod
    def _drop_unknown_steps(cls, value: Any) -> Any:
        if not isinstance(value, (list, tuple)):
            return []
        valid = {item.value for item in StepId}
        return [item for item in value if item in valid]


def load_state(context: dict[str, Any] | None) -> HeirState:
    raw = (context or {}).get(STATE_KEY)
    if not isinstance(raw, dict):
        return HeirState()
    try:
        return HeirState.model_validate(raw)
    except Exception:
        # 스키마가 바뀌었거나 프론트가 이상한 걸 보냈으면 대화를 깨는 대신
        # 새로 시작합니다.
        return HeirState()


def dump_state(state: HeirState) -> dict[str, Any]:
    return state.model_dump(mode="json")
