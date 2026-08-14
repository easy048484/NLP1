"""
가족관계 그래프 엔진 (공통모듈, 담당: 지원)

배우자/자녀 등 관계를 입력받아 법정상속분을 계산합니다.
지금은 3단계 개발 전이므로 최소 동작만 하는 placeholder입니다.
"""

from __future__ import annotations


def compute_legal_shares(spouse_alive: bool, num_children: int) -> dict[str, float]:
    """민법상 법정상속분 계산 (배우자 1.5 : 자녀 각 1 비율)의 최소 구현.

    실제로는 직계존속만 있는 경우, 형제자매 상속 등 더 많은 케이스를 다뤄야 하며
    3단계에서 본격적으로 구현합니다.
    """
    if num_children == 0:
        raise NotImplementedError("자녀가 없는 케이스는 3단계에서 구현 예정")

    spouse_share = 1.5 if spouse_alive else 0.0
    total_units = spouse_share + num_children
    child_unit = 1 / total_units

    result = {"child_each": round(child_unit, 4)}
    if spouse_alive:
        result["spouse"] = round((spouse_share / total_units), 4)
    return result
