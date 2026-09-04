"""
자산 목록 정리(asset_inventory) 체크리스트 전용 로컬 모델.

⚠️ develop의 공유 계약은 schemas.FinancialProfile(flat 집계)이다. 이 파일의
모델들은 그 계약과 이름만 겹치지 않게 의도적으로 "FinancialProfile" 래퍼를
두지 않는다 — 항목별(자산 하나하나, 부채 하나하나) 상세 정보를 체크리스트
진행 중에 담아두기 위한 순수 내부 모델일 뿐이고, 다른 에이전트로 넘길 때는
agent.py의 to_shared_profile()이 이 정보를 schemas.FinancialProfile의 flat
필드로 눌러서(요약해서) 내보낸다 — 그 과정에서 무엇이 사라지는지는
agent.py 상단 docstring에 정리돼 있다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AssetType = Literal["예금", "주식", "펀드", "부동산", "자동차", "퇴직연금", "기타"]
IncomeType = Literal["국민연금", "개인연금", "기타"]
LiabilityType = str
#: 3단계 금액 신뢰도. "미확인"(아직 언급 자체가 안 됨)은 이 타입에 없다 —
#: Asset 레코드 자체가 아직 존재하지 않는 상태라 별도 값이 필요 없다
#: (checked_categories/pending_categories로 이미 추적됨, agent.py 참고).
AmountConfidence = Literal["confirmed", "unknown_amount"]


class Asset(BaseModel):
    """스톡 자산. 부동산은 liquid를 명시하지 않으면 어댑터가 False로 처리
    (이 값 자체는 retirement_planner의 engine.py가 씀 — extra로 그대로 넘어감).

    confidence가 "unknown_amount"면 value는 항상 0(구조적 자리표시자일 뿐,
    실제 금액이 아님) — 순자산 계산에서 반드시 confidence로 걸러내고 써야
    한다(agent.py의 _format_summary/_to_shared_profile 참고). 그냥 value를
    더하면 "확인 안 됨"과 "확인했더니 0원"이 섞여 순자산이 실제보다 적어
    보이는 왜곡이 생긴다 — tax_calculator 때 "미확인은 0원이 아니다" 원칙과
    동일."""

    type: AssetType
    value: int = Field(ge=0, description="평가액 (원). confidence 설명 참고")
    liquid: bool | None = Field(
        default=None,
        description="None이면 유형별 기본값 적용 (부동산·자동차·퇴직연금=False, 그 외=True)",
    )
    return_rate: float | None = Field(
        default=None,
        description="사용자가 직접 입력한 연 명목수익률. 서비스가 기본값을 제시하지 않음",
    )
    confidence: AmountConfidence = Field(
        default="confirmed",
        description=(
            "confirmed=금액까지 확인됨(기존 동작과 동일 기본값). "
            "unknown_amount=존재는 확인됐지만 금액은 모름 — 사용자가 '몰라요'로"
            " 답했거나(생전 모드) 조회 기관이 존재만 확인해준 경우(사후 모드)."
            " 한 번 이 상태가 되면 영구적으로 취급하고 다시 캐묻지 않는다"
            "(부채/퇴직연금 후속질문의 '한 번만 묻고 종결' 원칙과 동일)."
        ),
    )


class IncomeStream(BaseModel):
    """플로우 소득. extractor.py의 LLM 폴백 경로가 만들 수 있으나, 지금
    체크리스트(예금/주식/펀드/부동산/부채)에는 소득 카테고리가 없어 이
    에이전트 자체는 적극적으로 수집하지 않는다 — extractor.py의 기존
    동작을 그대로 유지하기 위해 타입만 남겨둔다."""

    type: IncomeType
    monthly: int = Field(ge=0)
    start_age: int
    end_age: int | None = Field(default=None, description="None이면 종신")


class Liability(BaseModel):
    """부채. remaining_balance는 항상 필요 — 없으면 재질문 대상(조용한 실패
    금지 원칙, extractor.py 참고). monthly_payment/end_age는 사용자가
    자연스럽게 말했을 때만 채워지는 선택 정보다.

    confidence는 Asset.confidence와 완전히 같은 의미와 규칙이다 —
    "unknown_amount"면 remaining_balance는 항상 0(구조적 자리표시자일 뿐,
    실제 0원이 아님). "대출이 있어요" → "몰라요"처럼 존재는 확인됐지만
    금액을 모르는 경우이며, total_debts/순자산 계산에서 반드시 confidence로
    걸러내고 써야 한다(agent.py의 _format_summary/_to_shared_profile 참고).
    그냥 remaining_balance를 더하면 "확인 안 됨"과 "확인했더니 0원"이 섞여
    total_debts가 실제보다 적어 보이는 왜곡이 생긴다.

    ⚠️ schemas.FinancialProfile에는 이 필드들을 담을 자리가 없다 —
    total_debts 하나로만 내보내지므로, 정밀/단순 모드 구분과 confidence는
    extra로 itemized 리스트를 함께 넘겨야만 보존된다 (agent.py 참고)."""

    type: str = Field(description='"대출", "카드론", "전세자금대출" 등')
    remaining_balance: int = Field(
        ge=0, description="남은 원금 (원). confidence 설명 참고"
    )
    monthly_payment: int | None = Field(default=None, description="매월 상환액 (원)")
    end_age: int | None = Field(default=None, description="상환 종료 예상 나이")
    note: str | None = None
    confidence: AmountConfidence = Field(
        default="confirmed",
        description=(
            "confirmed=금액까지 확인됨(기존 동작과 동일 기본값). "
            "unknown_amount=존재는 확인됐지만 금액은 모름 — 사용자가 '몰라요'로"
            " 답한 경우. 한 번 이 상태가 되면 영구적으로 취급하고 다시 캐묻지"
            " 않는다(Asset.confidence와 동일 원칙)."
        ),
    )


class InsuranceTag(BaseModel):
    """사망보험금 등 — 노후 재원 계산에서 제외, decedent_estate/tax_calculator 전달용."""

    type: str
    value: int = Field(ge=0)
    note: str | None = None
