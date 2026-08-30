"""공유 재무정보를 세금 계산의 '확인 전 후보'로 변환한다.

공용 FinancialProfile이나 원본 목록을 변경하지 않는다. 이 모듈의 합계는
소유자·평가기준일·누락 여부 및 세법상 공제 자격을 확정한 값이 아니다.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from schemas import FinancialProfile

FINANCIAL_TYPES = {"예금", "적금", "주식", "펀드"}
PROFILE_FIELDS = (
    "real_estate_value",
    "financial_assets",
    "other_assets",
    "total_debts",
    "financial_debts",
)


def is_amount(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def tax_snapshot(profile: FinancialProfile) -> dict[str, Any] | None:
    """은퇴 나이 등의 변경은 상속세 재확인을 유발하지 않는다."""
    snapshot = {key: getattr(profile, key) for key in PROFILE_FIELDS}
    details = profile.extra.get("asset_organizer")
    if isinstance(details, dict):
        snapshot["items"] = deepcopy(details)
    if all(value is None for value in snapshot.values()):
        return None
    return snapshot


def _known_items(items: Any, amount_key: str) -> bool:
    # 빈 목록도 후보 0원일 뿐이다. 완전성은 대화에서 별도로 확인한다.
    return isinstance(items, list) and all(
        isinstance(item, dict)
        and is_amount(item.get(amount_key))
        and item.get("amount_status", "known") == "known"
        and not any(
            word in str(item.get("note", "")) for word in ("미언급", "미확인", "모름")
        )
        for item in items
    )


def _asset_kind(item: dict[str, Any]) -> str | None:
    kind = item.get("type")
    return kind.strip() if isinstance(kind, str) else None


def profile_candidates(snapshot: dict[str, Any]) -> tuple[dict[str, int], list[str]]:
    """항목별 자료가 존재하면 불완전해도 flat 합계로 우회하지 않는다."""
    candidates: dict[str, int] = {}
    warnings: list[str] = []
    items = snapshot.get("items")
    if not isinstance(items, dict):
        items = {}
    assets = items.get("assets")
    if "assets" in items:
        if _known_items(assets, "value"):
            candidates["original_inherited_property"] = sum(a["value"] for a in assets)
            unknown = {
                str(_asset_kind(a) or "미분류")
                for a in assets
                if _asset_kind(a) not in FINANCIAL_TYPES | {"부동산"}
            }
            if unknown:
                warnings.append(
                    "기타·미분류 자산은 전체 재산 후보에 포함되어 있지만 금융재산 "
                    "공제 여부는 미확인입니다: " + ", ".join(sorted(unknown))
                )
            else:
                candidates["financial_assets"] = sum(
                    a["value"] for a in assets if _asset_kind(a) in FINANCIAL_TYPES
                )
            if any(_asset_kind(a) == "주식" for a in assets):
                warnings.append(
                    "주식은 최대주주 등 보유주식의 공제 제외 여부를 확인해야 합니다."
                )
        else:
            warnings.append(
                "자산 목록에 금액 미확인·잘못된 항목이 있어 전체 합계를 자동 확정하지 않았습니다."
            )
    else:
        parts = [
            snapshot.get(k)
            for k in ("real_estate_value", "financial_assets", "other_assets")
        ]
        if all(is_amount(v) for v in parts):
            candidates["original_inherited_property"] = sum(parts)
        elif any(v is not None for v in parts):
            warnings.append(
                "공유 자산 합계가 일부만 채워져 전체 재산을 별도로 확인합니다."
            )
        if snapshot.get("financial_assets") is not None:
            warnings.append(
                "공유 financial_assets는 임시 0원 또는 일반 금융자산일 수 있어 공제대상 금액으로 자동 사용하지 않습니다."
            )

    liabilities = items.get("liabilities")
    if "liabilities" in items:
        if _known_items(liabilities, "remaining_balance"):
            candidates["debts"] = sum(d["remaining_balance"] for d in liabilities)
            # type='대출' 같은 상품 이름으로 금융기관 여부를 추측하지 않는다.
            kinds = [d.get("creditor_category") for d in liabilities]
            if all(
                isinstance(k, str) and k in {"financial_institution", "non_financial"}
                for k in kinds
            ):
                candidates["financial_debts"] = sum(
                    d["remaining_balance"]
                    for d in liabilities
                    if d.get("creditor_category") == "financial_institution"
                )
            else:
                warnings.append(
                    "채권자 구분이 없어 금융기관 채무 금액을 별도로 확인합니다."
                )
        else:
            warnings.append(
                "채무 목록에 미확인·잘못된 금액이 있어 합계를 별도로 확인합니다."
            )
    elif is_amount(snapshot.get("total_debts")):
        candidates["debts"] = snapshot["total_debts"]

    if items.get("insurance"):
        warnings.append(
            "보험 가입금액은 사망보험금이나 과세대상 금액과 다를 수 있어 자동 합산하지 않았습니다."
        )
    return candidates, warnings
