"""
AgentInput / AgentOutput 공통 계약.

개발 원칙 3 "계약(스키마)은 코드보다 먼저"에 따라, 오케스트레이터와 각 에이전트는
이 스키마로만 서로 대화합니다. 각 에이전트 내부 구현은 자유롭게 바꿔도 되지만,
이 인터페이스를 깨면 오케스트레이터가 즉시 실패하도록 해서 계약 변경을 팀 전체가
알아차릴 수 있게 합니다.

라우터 → 플래너 재설계(docs/라우팅방식변경.md)에서 추가된 것
---------------------------------------------------------------
- AgentAxis: 에이전트가 속한 축(생전준비 / 사후처리). 여러 에이전트가 한 요청에
  걸릴 때 축이 겹치면 Full Pipeline(LLM 분류 → DAG)로 올라갑니다.
- FinancialProfile: family_graph처럼 세션에 붙어사는 공유 재무 상태. 한 에이전트가
  물어본 자산 정보를 다른 에이전트가 재질문 없이 씁니다.
- HandoffRequest: "handoff:<이름>" 문자열을 구조화한 것. AgentOutput.handoffs에
  담습니다. 기존 next_action 문자열도 계속 받아들이며(오케스트레이터가 파싱),
  handoffs가 비어 있고 next_action이 "handoff:x" 형식이면 그것을 씁니다.
- ChatResponse: /chat 응답. 여러 에이전트가 실행됐을 때 어떤 에이전트들이
  어떤 경로(fast/standard/full)로 돌았고 숫자 검증이 통과했는지를 담습니다.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentName(str, Enum):
    HEIR_NAVIGATOR = "heir_navigator"  # 상속인 절차 내비게이터
    DECEDENT_ESTATE = "decedent_estate"  # 피상속인 유언장·자산정리
    TAX_CALCULATOR = "tax_calculator"  # 상속세 계산·설계
    # ---- 아래 두 개는 껍데기(stub)만 등록돼 있습니다. 담당 팀원이 agents/<이름>/agent.py
    #      의 run()을 채우면 오케스트레이터 수정 없이 그대로 편입됩니다.
    RETIREMENT_PLANNER = "retirement_planner"  # 은퇴자금 설계 (생전준비)
    ASSET_ORGANIZER = "asset_organizer"  # 자산 목록 정리 (생전준비)


class AgentAxis(str, Enum):
    PRE_NEED = "pre_need"  # 생전 준비
    POST_DEATH = "post_death"  # 사후 처리


class FinancialProfile(BaseModel):
    """세션 단위로 공유되는 재무 상태.

    tax_calculator의 InheritanceTaxInput 중 "자산" 성격의 필드와, 은퇴자금 설계에
    필요한 최소 필드를 모았습니다. 모든 필드는 선택이며, 에이전트는 자기가 알게
    된 값만 채워서 AgentOutput.financial_profile로 돌려주면 오케스트레이터가
    세션의 기존 값과 병합(None이 아닌 값만 덮어씀)합니다.
    """

    # 자산 (원)
    real_estate_value: Optional[int] = Field(
        default=None, description="부동산 평가액(원)"
    )
    financial_assets: Optional[int] = Field(default=None, description="금융재산(원)")
    financial_debts: Optional[int] = Field(default=None, description="금융채무(원)")
    other_assets: Optional[int] = Field(default=None, description="기타 자산(원)")
    total_debts: Optional[int] = Field(default=None, description="총 채무(원)")
    # 은퇴 설계
    current_age: Optional[int] = Field(default=None, description="현재 나이")
    retirement_age: Optional[int] = Field(default=None, description="희망 은퇴 나이")
    monthly_income: Optional[int] = Field(default=None, description="월 소득(원)")
    monthly_expense: Optional[int] = Field(default=None, description="월 생활비(원)")
    monthly_pension: Optional[int] = Field(default=None, description="예상 월 연금(원)")
    # 스키마에 아직 없는 값을 에이전트끼리 주고받을 자리
    extra: dict[str, Any] = Field(default_factory=dict)

    def merged_with(self, other: Optional["FinancialProfile"]) -> "FinancialProfile":
        """other의 None이 아닌 값으로 self를 덮어쓴 새 프로필."""
        if other is None:
            return self.model_copy(deep=True)
        update = {
            k: v
            for k, v in other.model_dump().items()
            if v is not None and k != "extra"
        }
        merged = self.model_copy(update=update, deep=True)
        merged.extra = {**self.extra, **other.extra}
        return merged


class HandoffRequest(BaseModel):
    target: AgentName
    reason: Optional[str] = None
    priority: int = Field(
        default=0, description="클수록 우선. 여러 개면 가장 큰 것이 다음 턴 대상"
    )


class AgentInput(BaseModel):
    session_id: str
    user_message: str
    family_graph: Optional[dict[str, Any]] = Field(
        default=None, description="가족관계 그래프 엔진이 계산한 현재 상태"
    )
    family_graph_id: Optional[str] = Field(
        default=None,
        description=(
            "DB에 저장된 family_graph의 식별자. 오케스트레이터가 이 값으로 "
            "family_graph 테이블을 조회해서 위 family_graph 필드를 채웁니다 — "
            "family_graph를 직접 채워 보내면(테스트/레거시 클라이언트) 그 값이 "
            "우선합니다. 프론트는 이 값을 세션과 별도로 (localStorage 등에) "
            "저장해뒀다가 매 요청에 실어 보내야 재방문 시 가족관계를 다시 "
            "입력하지 않아도 됩니다."
        ),
    )
    financial_profile: Optional[FinancialProfile] = Field(
        default=None,
        description=(
            "세션 공유 재무 상태. 요청에 담아 보내면 세션 값과 병합되어 이번 턴의 "
            "모든 에이전트에 전달됩니다. 보통은 비워두고 세션 값을 씁니다."
        ),
    )
    context: dict[str, Any] = Field(default_factory=dict)
    image_base64: Optional[str] = Field(
        default=None,
        description=(
            "판독할 이미지(예: 유언장 사진)의 base64 인코딩 데이터. "
            "지원 포맷·용량 제한 등 세부 검증은 각 에이전트가 담당한다 — "
            "이 스키마는 필드 존재 여부만 규약화한다. 서버는 이 값을 "
            "저장하지 않고 판독 직후 폐기해야 한다."
        ),
    )
    image_media_type: Optional[str] = Field(
        default=None,
        description="image_base64의 MIME 타입 (예: image/jpeg). image_base64와 함께 온다.",
    )


class AgentOutput(BaseModel):
    agent: AgentName
    reply: str
    next_action: Optional[str] = Field(
        default=None,
        description=(
            "에이전트 수준 힌트. 'handoff:<에이전트이름>'(레거시 핸드오프 형식) 또는 "
            "'await_user_confirmation' 같은 자유 문자열. 새 코드는 handoffs를 쓰세요."
        ),
    )
    handoffs: list[HandoffRequest] = Field(
        default_factory=list,
        description="다음 턴을 넘길 에이전트 요청 목록 (priority가 큰 것이 우선)",
    )
    financial_profile: Optional[FinancialProfile] = Field(
        default=None,
        description="이번 턴에 새로 알게 된 재무 정보. 세션 프로필에 병합됩니다.",
    )
    data: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    """compose 단계의 숫자·날짜 검증 결과 (orchestrator/compose.py)."""

    ok: bool
    mode: str = Field(
        description="single | synthesized | concat | concat_after_failure"
    )
    mismatches: list[str] = Field(default_factory=list)


class ChatResponse(AgentOutput):
    """/chat 응답. AgentOutput의 상위 호환 — 기존 필드는 그대로, 실행 메타를 추가."""

    agents: list[AgentName] = Field(
        default_factory=list, description="이번 턴에 실제로 실행된 에이전트(실행 순서)"
    )
    path: str = Field(default="standard", description="fast | standard | full")
    verification: Optional[VerificationResult] = None
