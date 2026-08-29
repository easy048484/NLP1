"""유류분 1차 시뮬레이션의 입력·출력 모델."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class AnalysisStage(str, Enum):
    PRE_DEATH = "pre_death"
    POST_DEATH = "post_death"


class AnalysisStatus(str, Enum):
    BASIC_ESTIMATE = "basic_estimate"
    NO_SIMPLE_GAP = "no_simple_gap"
    POSSIBLE_GAP = "possible_gap"
    EXPERT_REVIEW_REQUIRED = "expert_review_required"


class ComplexityFlag(str, Enum):
    PRIOR_GIFT = "prior_gift"
    SPECIAL_BENEFIT = "special_benefit"
    CONTRIBUTION_SHARE = "contribution_share"
    RENUNCIATION_OR_DISQUALIFICATION = "renunciation_or_disqualification"
    REPRESENTATION_INHERITANCE = "representation_inheritance"
    VALUATION_DISPUTE = "valuation_dispute"
    FOREIGN_ELEMENT = "foreign_element"
    USER_REPORTED_COMPLEX_CASE = "user_reported_complex_case"


class HeirShareInput(BaseModel):
    """사용자가 확인한 값만 담는 유류분 시뮬레이션 입력."""

    stage: AnalysisStage = AnalysisStage.PRE_DEATH
    estate_value: int = Field(ge=0, description="현재 또는 상속개시 당시 재산가액")
    debts: int = Field(default=0, ge=0, description="확인된 채무")
    confirmed_included_gifts: int = Field(
        default=0,
        ge=0,
        description="전문가 또는 확인 자료로 산입 대상이 명확한 증여재산",
    )
    planned_acquisitions: dict[str, int] = Field(
        default_factory=dict,
        description="유언 등에 따라 각 사람이 받을 예정 금액",
    )
    inheritance_opening_date: Optional[date] = Field(
        default=None, description="사망 후 점검이면 상속개시일(사망일)"
    )
    complexity_flags: list[ComplexityFlag] = Field(default_factory=list)

    @field_validator("planned_acquisitions")
    @classmethod
    def validate_planned_acquisitions(cls, value: dict[str, int]) -> dict[str, int]:
        cleaned: dict[str, int] = {}
        for name, amount in value.items():
            normalized_name = str(name).strip()
            if not normalized_name:
                raise ValueError("예정 취득자의 이름은 비워둘 수 없습니다.")
            if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
                raise ValueError("예정 취득액은 0원 이상의 정수여야 합니다.")
            cleaned[normalized_name] = amount
        return cleaned


class HeirShareBreakdown(BaseModel):
    name: str
    relation: str
    statutory_share_fraction: str
    statutory_share_amount: int
    forced_share_rate_fraction: str
    basic_forced_share_estimate: int
    planned_acquisition: Optional[int] = None
    simple_gap: Optional[int] = None


class ExpertHandoffSummary(BaseModel):
    case_stage: AnalysisStage
    inheritance_opening_date: Optional[date]
    family_summary: list[str]
    asset_summary: list[str]
    planned_distribution: dict[str, int]
    per_heir_calculation: list[HeirShareBreakdown]
    possible_gap_heirs: list[str]
    review_points: list[str]
    documents_to_prepare: list[str]


class HeirShareResult(BaseModel):
    status: AnalysisStatus
    rule_version: str
    rule_effective_from: date
    basis_amount: int
    heirs: list[HeirShareBreakdown]
    assumptions: list[str]
    warnings: list[str]
    legal_sources: list[str]
    expert_handoff: ExpertHandoffSummary


Relation = Literal["spouse", "child", "parent", "grandchild", "sibling", "grandparent"]


class FamilyMember(BaseModel):
    name: str = Field(min_length=1)
    relation: Relation
    alive: bool = True
    minor: bool = False
