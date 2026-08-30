"""법정상속분과 기본 유류분을 계산하는 결정론적 엔진.

법정상속인 선택·법정상속분 계산은 공용 모듈(family_graph.heirs)에 위임한다 —
tax_calculator/heir_navigator 와 같은 규칙을 쓰기 위해서다. 이 파일은 유류분
쪽 계산(기초액·유류분율·예정취득액 비교·전문가 핸드오프 요약)만 담당한다.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from family_graph.heirs import UnsupportedFamilyCase as UnsupportedFamilyCase
from family_graph.heirs import classify_heirs, select_legal_heirs

from .models import (
    AnalysisStage,
    AnalysisStatus,
    ExpertHandoffSummary,
    HeirShareBreakdown,
    HeirShareInput,
    HeirShareResult,
)
from .rules import (
    COMPLEXITY_LABELS,
    DOCUMENTS_TO_PREPARE,
    FORCED_SHARE_RATES,
    LEGAL_SOURCE_URLS,
    RULE_EFFECTIVE_FROM,
    RULE_VERSION,
)

# 하위호환: 이 두 이름을 calculator 에서 import 하던 코드가 계속 동작하도록 re-export.
__all__ = [
    "UnsupportedFamilyCase",
    "select_legal_heirs",
    "calculate_heir_share",
]


def _fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def _money_by_fraction(amount: int, fraction: Fraction) -> int:
    return amount * fraction.numerator // fraction.denominator


def calculate_heir_share(
    data: HeirShareInput,
    family_graph: dict[str, Any] | None,
) -> HeirShareResult:
    """기본 유류분과 유언상 예정 취득액의 단순 차이를 계산한다."""

    classification = classify_heirs(family_graph)
    if not classification.has_family_data:
        raise UnsupportedFamilyCase(
            "가족관계 정보가 없어 법정상속분을 계산할 수 없습니다."
        )
    if classification.unsupported_reason:
        raise UnsupportedFamilyCase(classification.unsupported_reason)

    legal_heirs = classification.legal_heirs
    statutory_shares = classification.statutory_shares
    basis_amount = max(
        0, data.estate_value + data.confirmed_included_gifts - data.debts
    )

    warnings: list[str] = []
    assumptions = [
        "사용자가 입력한 재산·채무 금액이 정확하다고 가정했습니다.",
        "1원 미만의 나눗셈 차이는 버림 처리했습니다.",
        "특별수익·기여분·상속포기·대습상속 등은 자동 판단하지 않습니다.",
    ]
    review_points = [COMPLEXITY_LABELS[flag] for flag in data.complexity_flags]

    if data.stage == AnalysisStage.PRE_DEATH:
        warnings.append(
            "생전 점검 결과는 현재 가족관계와 재산을 기준으로 한 예상치입니다."
        )
    elif data.inheritance_opening_date is None:
        review_points.append("상속개시일(사망일) 확인 필요")
    elif data.inheritance_opening_date < RULE_EFFECTIVE_FROM:
        review_points.append(
            "현재 규칙 시행일 이전 상속이므로 당시 적용 법령 확인 필요"
        )

    if data.confirmed_included_gifts > 0:
        review_points.append("증여재산의 수증자별 특별수익과 실제 산입 범위 확인 필요")

    planned_total = sum(data.planned_acquisitions.values())
    if data.planned_acquisitions and planned_total > data.estate_value:
        review_points.append("예정 취득액 합계가 입력한 상속재산을 초과함")

    breakdowns: list[HeirShareBreakdown] = []
    possible_gap_heirs: list[str] = []
    for heir in legal_heirs:
        statutory_share = statutory_shares[heir.name]
        forced_share_rate = FORCED_SHARE_RATES.get(heir.relation, Fraction(0, 1))
        statutory_amount = _money_by_fraction(basis_amount, statutory_share)
        basic_forced_share = _money_by_fraction(statutory_amount, forced_share_rate)

        planned_acquisition: int | None = None
        simple_gap: int | None = None
        if data.planned_acquisitions:
            planned_acquisition = data.planned_acquisitions.get(heir.name, 0)
            simple_gap = max(0, basic_forced_share - planned_acquisition)
            if simple_gap > 0:
                possible_gap_heirs.append(heir.name)

        breakdowns.append(
            HeirShareBreakdown(
                name=heir.name,
                relation=heir.relation,
                statutory_share_fraction=_fraction_text(statutory_share),
                statutory_share_amount=statutory_amount,
                forced_share_rate_fraction=_fraction_text(forced_share_rate),
                basic_forced_share_estimate=basic_forced_share,
                planned_acquisition=planned_acquisition,
                simple_gap=simple_gap,
            )
        )

    if review_points:
        status = AnalysisStatus.EXPERT_REVIEW_REQUIRED
    elif not data.planned_acquisitions:
        status = AnalysisStatus.BASIC_ESTIMATE
    elif possible_gap_heirs:
        status = AnalysisStatus.POSSIBLE_GAP
    else:
        status = AnalysisStatus.NO_SIMPLE_GAP

    family_summary = [
        f"{heir.name}: {heir.relation}, 법정상속분 {statutory_shares[heir.name]}"
        for heir in legal_heirs
    ]
    asset_summary = [
        f"입력 재산가액: {data.estate_value}원",
        f"확인된 산입 증여재산: {data.confirmed_included_gifts}원",
        f"확인된 채무: {data.debts}원",
        f"단순 유류분 산정 기초액: {basis_amount}원",
    ]

    handoff_review_points = list(review_points)
    if possible_gap_heirs:
        warnings.append(
            "일부 상속인에게 기본 유류분보다 적게 배분될 가능성이 있습니다."
        )
        handoff_review_points.append(
            "단순 부족 예상액의 실제 청구 가능 여부·상대방·최종 반환 금액 확인 필요"
        )
    if review_points:
        warnings.append(
            "복잡한 사실관계가 있어 실제 청구 가능 여부와 금액은 변호사 검토가 필요합니다."
        )

    return HeirShareResult(
        status=status,
        rule_version=RULE_VERSION,
        rule_effective_from=RULE_EFFECTIVE_FROM,
        basis_amount=basis_amount,
        heirs=breakdowns,
        assumptions=assumptions,
        warnings=warnings,
        legal_sources=LEGAL_SOURCE_URLS,
        expert_handoff=ExpertHandoffSummary(
            case_stage=data.stage,
            inheritance_opening_date=data.inheritance_opening_date,
            family_summary=family_summary,
            asset_summary=asset_summary,
            planned_distribution=data.planned_acquisitions,
            per_heir_calculation=breakdowns,
            possible_gap_heirs=possible_gap_heirs,
            review_points=handoff_review_points,
            documents_to_prepare=list(DOCUMENTS_TO_PREPARE),
        ),
    )
