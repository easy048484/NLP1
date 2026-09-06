"""상속세 계산 결과와 오류를 사용자에게 보여주는 문구 계층."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError


FIELD_LABELS = {
    "original_inherited_property": "전체 상속재산",
    "deemed_inherited_property": "보험금·퇴직금 등 함께 계산되는 재산",
    "estimated_inherited_property": "추가로 확인된 상속재산",
    "debts": "대출과 그 밖의 빚",
    "financial_assets": "예금·주식 등 금융재산",
    "financial_debts": "금융기관에서 빌린 금액",
    "prior_gifts_to_heirs": "상속인에게 미리 증여한 재산",
    "prior_gifts_to_non_heirs": "상속인이 아닌 사람에게 미리 증여한 재산",
    "spouse_actual_inheritance": "배우자가 실제로 받는 재산",
}


ERROR_MESSAGES = (
    (
        "배우자가 없으면 배우자 단독상속",
        "배우자가 없다고 입력했지만 배우자에게 돌아가는 재산 정보도 함께 "
        "입력되어 있어요. 배우자 유무와 배우자가 받는 금액을 다시 확인해주세요.",
    ),
    (
        "배우자 단독상속과 자녀 공동상속",
        "배우자만 상속받는다고 입력했지만 생존 자녀 수도 함께 입력되어 있어요. "
        "가족관계 정보를 다시 확인해주세요.",
    ),
    (
        "금융재산가액은 총상속재산가액보다",
        "예금·주식 등 금융재산으로 입력한 금액이 전체 상속재산보다 커요. "
        "두 금액을 다시 확인해주세요.",
    ),
    (
        "금융채무가액은 전체 채무가액보다",
        "금융기관에서 빌린 금액이 전체 빚보다 커요. 두 금액을 다시 확인해주세요.",
    ),
    (
        "비과세재산과 과세가액 불산입 재산의 합계",
        "세금 계산에서 제외할 재산의 합계가 전체 상속재산보다 커요. "
        "제외할 금액과 전체 재산을 다시 확인해주세요.",
    ),
    (
        "비상속인 유증액과 후순위 상속재산의 합계",
        "상속인이 아닌 사람이나 다음 순위 가족에게 돌아가는 금액의 합계가 "
        "전체 상속재산보다 커요. 입력 금액을 다시 확인해주세요.",
    ),
    (
        "사전증여재산의 증여세 과세표준",
        "미리 증여한 재산 중 세금 계산에 반영할 금액이 실제 증여 금액보다 "
        "커요. 두 금액을 다시 확인해주세요.",
    ),
    (
        "현재 배우자공제는",
        "현재 계산기는 배우자와 자녀가 함께 상속받거나 배우자만 상속받는 "
        "경우까지 계산할 수 있어요. 다른 가족관계라면 세무 전문가의 확인이 필요해요.",
    ),
)


WARNING_MESSAGES = {
    "상속개시일이 없어 신고기한을 계산하지 않았습니다.": (
        "돌아가신 날짜를 입력하지 않아 신고기한은 계산하지 않았어요."
    ),
    "기한 내 신고 여부는 사용자가 입력한 값을 그대로 사용했습니다.": (
        "기한 안에 신고할 예정인지에 대해서는 입력하신 답변을 그대로 반영했어요."
    ),
    "가업·영농·재해·동거주택 공제는 입력 금액을 반영했으며 법적 요건은 판단하지 않았습니다.": (
        "특별한 사유로 추가 공제받는 금액은 입력하신 그대로 반영했으며, "
        "실제 적용 조건까지 확인한 것은 아니에요."
    ),
    "그 밖의 세액공제는 입력 금액을 반영했으며 공제 자격과 증빙은 확인하지 않았습니다.": (
        "추가로 세금에서 줄어드는 금액은 입력하신 그대로 반영했으며, "
        "적용 조건과 증빙까지 확인한 것은 아니에요."
    ),
}

PRE_NEED_WARNING_MESSAGES = {
    "상속개시일이 없어 신고기한을 계산하지 않았습니다.": (
        "생전 시뮬레이션이므로 실제 상속개시일에 따른 신고기한은 " "계산하지 않았어요."
    ),
}


def won(value: int) -> str:
    """원 단위 금액을 읽기 쉬운 형식으로 표시한다."""

    return f"{value:,}원"


def friendly_warning(message: str, axis: str | None = None) -> str:
    """내부 경고를 사용자에게 보여줄 쉬운 문장으로 바꾼다."""

    if axis == "pre_need":
        return PRE_NEED_WARNING_MESSAGES.get(
            message, WARNING_MESSAGES.get(message, message)
        )
    return WARNING_MESSAGES.get(message, message)


def result_reply(result: Any, axis: str | None = None) -> str:
    """상속세 계산 결과를 쉬운 항목명으로 표시한다."""

    lines = [
        "입력하신 정보로 예상 상속세를 계산했어요.",
        "",
        f"- 상속재산으로 계산된 전체 금액: {won(result.total_inherited_property)}",
        f"- 빚과 인정되는 비용: {won(result.deductible_expenses)}",
        f"- 세금 계산에 반영되는 재산 금액: {won(result.taxable_inheritance_value)}",
        f"- 기본·배우자 등으로 공제되는 금액: {won(result.total_inheritance_deduction)}",
        f"- 세금을 매기는 기준 금액: {won(result.inheritance_tax_base)}",
        f"- 세율을 적용해 계산한 세금: {won(result.calculated_inheritance_tax)}",
        f"- 기한 내 신고로 줄어드는 금액: {won(result.filing_tax_credit)}",
        f"- 최종 예상 상속세: {won(result.estimated_tax_due)}",
    ]

    if result.estimated_filing_deadline is not None:
        lines.extend(
            [
                "",
                f"예상 신고기한은 {result.estimated_filing_deadline.isoformat()}입니다.",
            ]
        )

    if result.warnings:
        lines.append("")
        lines.append("확인할 사항:")

        for warning in result.warnings:
            lines.append(f"- {friendly_warning(warning, axis)}")

    lines.extend(
        [
            "",
            (
                "이 결과는 현재 입력한 정보에 따른 참고용 계산입니다. "
                "실제 신고 전에는 홈택스 또는 세무 전문가를 통해 확인해주세요."
            ),
        ]
    )

    return "\n".join(lines)


def _validation_error_message(exc: ValidationError) -> str | None:
    """필드 단위 입력 오류를 사용자가 고칠 수 있는 문장으로 바꾼다."""

    for error in exc.errors():
        location = error.get("loc", ())
        field_name = location[-1] if location else None
        error_type = str(error.get("type", ""))

        if isinstance(field_name, str) and error_type in {
            "greater_than_equal",
            "int_parsing",
            "int_type",
        }:
            label = FIELD_LABELS.get(field_name, "금액 입력란")
            return f"{label}에는 0원 이상의 숫자를 입력해주세요."

    return None


def user_error_reply(exc: ValidationError | ValueError) -> str:
    """원본 예외를 노출하지 않고 사용자가 수정할 내용을 안내한다."""

    raw_message = str(exc)

    for fragment, friendly_message in ERROR_MESSAGES:
        if fragment in raw_message:
            return f"입력 내용을 다시 확인해주세요.\n\n{friendly_message}"

    if isinstance(exc, ValidationError):
        validation_message = _validation_error_message(exc)

        if validation_message is not None:
            return f"입력 내용을 다시 확인해주세요.\n\n{validation_message}"

    return (
        "입력한 정보 중 계산에 사용할 수 없는 값이 있어요. "
        "각 금액이 0원 이상인지, 세부 금액이 전체 금액보다 크지 않은지 "
        "다시 확인해주세요."
    )
