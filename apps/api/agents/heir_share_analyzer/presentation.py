"""유류분 시뮬레이션 결과를 쉬운 말로 설명한다."""

from __future__ import annotations

from .models import AnalysisStatus, HeirShareResult


def format_won(amount: int) -> str:
    return f"{amount:,}원"


def result_reply(result: HeirShareResult) -> str:
    if result.status == AnalysisStatus.POSSIBLE_GAP:
        headline = "단순 계산상 유류분 부족 가능성이 발견되었습니다."
    elif result.status == AnalysisStatus.EXPERT_REVIEW_REQUIRED:
        headline = "복잡한 조건이 있어 전문가 검토가 필요합니다."
    elif result.status == AnalysisStatus.NO_SIMPLE_GAP:
        headline = "단순 비교에서는 유류분 부족 신호가 발견되지 않았습니다."
    else:
        headline = "기본 유류분 예상액을 계산했습니다."

    lines = [
        headline,
        "",
        f"유류분 산정 기초액(단순 계산): {format_won(result.basis_amount)}",
        "",
        "상속인별 1차 계산",
    ]
    for heir in result.heirs:
        detail = (
            f"- {heir.name}: 법정상속분 {heir.statutory_share_fraction}, "
            f"기본 유류분 예상액 {format_won(heir.basic_forced_share_estimate)}"
        )
        if heir.planned_acquisition is not None and heir.simple_gap is not None:
            detail += (
                f", 예정 취득액 {format_won(heir.planned_acquisition)}, "
                f"단순 부족 예상액 {format_won(heir.simple_gap)}"
            )
        lines.append(detail)

    if not any(heir.planned_acquisition is not None for heir in result.heirs):
        lines.extend(
            [
                "",
                "유언장상 예정 취득액이 아직 없어 부족 가능성 비교는 하지 않았습니다.",
            ]
        )

    if result.expert_handoff.review_points:
        lines.extend(["", "전문가가 확인해야 할 사항"])
        lines.extend(f"- {point}" for point in result.expert_handoff.review_points)

    lines.extend(
        [
            "",
            "이 결과는 법률 판단이나 실제 청구 가능 금액이 아닌 참고용 1차 시뮬레이션입니다.",
            "실제 증여 산입 범위, 특별수익·기여분, 청구 상대방과 최종 금액은 변호사가 확인해야 합니다.",
        ]
    )
    return "\n".join(lines)


def unsupported_reply(reason: str) -> str:
    return (
        "현재 가족관계만으로는 유류분을 안전하게 계산하기 어렵습니다.\n\n"
        f"확인이 필요한 이유: {reason}\n\n"
        "잘못된 지분을 제시하지 않고 전문가 검토가 필요한 사례로 표시했습니다. "
        "가족관계 자료, 유언장, 재산·채무 및 사전증여 자료를 준비해 변호사에게 "
        "확인받는 것이 좋습니다."
    )
