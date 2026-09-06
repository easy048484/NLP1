"""
AgentInput / AgentOutput 공통 계약.

개발 원칙 3 "계약(스키마)은 코드보다 먼저"에 따라, 오케스트레이터와 각 에이전트는
이 스키마로만 서로 대화합니다. 각 에이전트 내부 구현은 자유롭게 바꿔도 되지만,
이 인터페이스를 깨면 오케스트레이터가 즉시 실패하도록 해서 계약 변경을 팀 전체가
알아차릴 수 있게 합니다.

라우터 → 플래너 재설계(docs/라우팅방식변경.md)에서 추가된 것
---------------------------------------------------------------
- AgentAxis: 에이전트가 담당하는 상담 축(생전준비 / 사후처리). AgentSpec.axes에
  하나 이상 선언하며, 양쪽을 담당하면 두 값을 모두 넣습니다. 여러 에이전트가 한
  요청에 걸릴 때 축이 겹치면 Full Pipeline(LLM 분류 → DAG)로 올라갑니다.
- FinancialProfile(별칭 Estate): family_graph처럼 세션에 붙어사는 공유 상태.
  "피상속인의 상속재산" — 생전엔 본인 것, 사후엔 고인의 것(상속인이 안심상속
  조회 등으로 파악). 한 에이전트가 물어본 자산 정보를 다른 에이전트가 재질문
  없이 씁니다.
- WillStatus: decedent_estate가 판정한 유언장 상태 요약. FinancialProfile처럼
  세션에 붙어 tax_calculator·heir_share_analyzer가 재질문 없이 참고합니다.
- HandoffRequest: "handoff:<이름>" 문자열을 구조화한 것. AgentOutput.handoffs에
  담습니다. 기존 next_action 문자열도 계속 받아들이며(오케스트레이터가 파싱),
  handoffs가 비어 있고 next_action이 "handoff:x" 형식이면 그것을 씁니다.
- ChatResponse: /chat 응답. 여러 에이전트가 실행됐을 때 어떤 에이전트들이
  어떤 경로(fast/standard/full)로 돌았고 숫자 검증이 통과했는지를 담습니다.
- AgentInput.axis: 프론트 온보딩 "상담 구분"(생전 준비 / 사후 절차). 키워드
  후보가 없거나 애매할 때 라우팅 편향에 씁니다.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class AgentName(str, Enum):
    HEIR_NAVIGATOR = "heir_navigator"  # 상속인 절차 내비게이터
    DECEDENT_ESTATE = "decedent_estate"  # 피상속인 유언장·자산정리
    TAX_CALCULATOR = "tax_calculator"  # 상속세 계산·설계
    HEIR_SHARE_ANALYZER = "heir_share_analyzer"  # 법정상속분·유류분 위험 점검
    # ---- 아래 두 개는 껍데기(stub)만 등록돼 있습니다. 담당 팀원이 agents/<이름>/agent.py
    #      의 run()을 채우면 오케스트레이터 수정 없이 그대로 편입됩니다.
    RETIREMENT_PLANNER = "retirement_planner"  # 은퇴자금 설계 (생전준비)
    ASSET_ORGANIZER = "asset_organizer"  # 자산 목록 정리 (생전준비)


class AgentAxis(str, Enum):
    PRE_NEED = "pre_need"  # 생전 준비
    POST_DEATH = "post_death"  # 사후 처리


class FinancialProfile(BaseModel):
    """세션 단위로 공유되는 **피상속인의 상속재산**(별칭 Estate).

    생전 여정에서는 사용자(피상속인 본인)의 재산·부채이고, 사후 여정에서는
    상속인이 안심상속 통합조회 등으로 파악한 고인의 재산·부채입니다. 두 경우
    모두 "상속의 대상이 되는 재산"이라는 의미는 같습니다.

    asset_organizer가 이 값을 채우는 유일한 에이전트이고, tax_calculator·
    heir_share_analyzer·retirement_planner가 재질문 없이 읽습니다. 모든 필드는
    선택이며, 에이전트는 자기가 알게 된 값만 채워서 AgentOutput.financial_profile
    로 돌려주면 오케스트레이터가 세션의 기존 값과 병합(None이 아닌 값만 덮어씀)
    합니다.

    ⚠️ current_age 이하 5개 "은퇴 설계" 필드는 retirement_planner 전용이라
    상속재산 개념과는 결이 다릅니다 — PR #45(asset_organizer/retirement_planner)
    머지 후 retirement_planner 자체 상태로 분리 예정.
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


#: 의미를 그대로 드러내는 별칭. 코드에서 `Estate` 로 참조해도 되고, 향후 하드
#: 리네임 시 이 별칭이 이행 지점이 됩니다 (schemas/__init__.py 도 함께 export).
Estate = FinancialProfile


class WillStatus(BaseModel):
    """decedent_estate 가 판정한 유언장 상태 요약.

    family_graph / financial_profile 과 같은 방식으로 세션에 붙어, 같은 세션의
    tax_calculator·heir_share_analyzer 가 "유언장이 있는지 / 효력이 있는지"를
    재질문 없이 참고합니다. 유언장 원문·개인정보는 담지 않습니다
    (decedent_estate 저장 정책 C안 — 판정 요약만).
    """

    #: decedent_estate 가 이번 세션에서 유언장을 실제로 점검했는지.
    checked: bool = False
    #: 민법 5방식 id, "unknown", 또는 유언장 없음이면 None.
    will_type: Optional[str] = None
    #: 유언장이 없는 것으로 확인됨.
    no_will: bool = False
    #: 요건 판정 종합 등급.
    overall_grade: Optional[Literal["green", "yellow", "red"]] = None
    #: green → True, red → False, 그 외(미확인·쟁점) → None.
    has_effect: Optional[bool] = None

    def merged_with(self, other: Optional["WillStatus"]) -> "WillStatus":
        """other 가 실제 점검 결과(checked=True)면 그것으로, 아니면 self 유지."""
        if other is None or not other.checked:
            return self.model_copy(deep=True)
        return other.model_copy(deep=True)


class HandoffRequest(BaseModel):
    target: AgentName
    reason: Optional[str] = None
    priority: int = Field(
        default=0, description="클수록 우선. 여러 개면 가장 큰 것이 다음 턴 대상"
    )


class AgentInput(BaseModel):
    session_id: str
    user_message: str
    axis: Optional[Literal["pre_need", "post_death"]] = Field(
        default=None,
        description=(
            "프론트 온보딩 '상담 구분'. pre_need=생전 준비, post_death=사후 절차. "
            "키워드 후보가 없거나 애매할 때 오케스트레이터가 라우팅 편향에 씁니다."
        ),
    )
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
            "세션 공유 상속재산(Estate). 요청에 담아 보내면 세션 값과 병합되어 "
            "이번 턴의 모든 에이전트에 전달됩니다. 보통은 비워두고 세션 값을 씁니다."
        ),
    )
    will_status: Optional[WillStatus] = Field(
        default=None,
        description=(
            "세션 공유 유언장 판정 요약(decedent_estate 산출). 오케스트레이터가 "
            "세션 값으로 채워 넣으므로 프론트는 보통 비워둡니다."
        ),
    )
    history: list[dict[str, str]] = Field(
        default_factory=list,
        description=(
            "이 세션의 대화 원문 (시간순, 마지막 원소가 이번 턴 user_message). "
            "[{'role': 'user'|'assistant', 'content': str}, ...] 형식이고 "
            "오케스트레이터가 세션에서 채워 넣으므로 프론트는 비워둡니다. "
            "슬롯 추출기가 '어제'처럼 앞 문맥이 있어야 해석되는 답변을 읽는 데 "
            "씁니다 — 이력 없이 마지막 한 줄만 보면 같은 질문을 반복하게 됩니다. "
            "길이 상한은 오케스트레이터(session_store._HISTORY_MAX_*)가 겁니다."
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
        description="이번 턴에 새로 알게 된 상속재산 정보. 세션 값에 병합됩니다.",
    )
    will_status: Optional[WillStatus] = Field(
        default=None,
        description=(
            "이번 턴에 판정한 유언장 상태(decedent_estate만 채움). 세션 값에 "
            "병합됩니다."
        ),
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
    contributions: list[AgentOutput] = Field(
        default_factory=list,
        description=(
            "에이전트별 원본 출력(실행 순서). 프론트는 카드 렌더에 이것만 쓰면 "
            "된다 — 최상위 data 평면 병합은 겹치는 키(pending_questions 등)가 "
            "나중 값으로 덮이는 전환기 레거시라, 구버전 클라이언트 호환용으로만 "
            "유지된다."
        ),
    )
    path: str = Field(default="standard", description="fast | standard | full")
    verification: Optional[VerificationResult] = None
