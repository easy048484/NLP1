"""가족관계 그래프 → 법정상속인 분류 (공용 모듈).

tax_calculator / heir_share_analyzer / heir_navigator 가 각자 재구현하던
"heirs 목록에서 법정상속인을 순위대로 골라낸다" 로직을 한 곳에 모았습니다.
경계 사례(대습상속 등)에서 서로 다르게 동작하던 문제를 없애기 위함입니다.

기준: 민법 제1000조(상속 순위)·제1003조(배우자 상속)·제1009조(법정상속분).
MVP 가 **안전하게 구분할 수 있는 경우만** 계산하고, 나머지는
``unsupported_reason`` 으로 돌려줍니다 — 잘못된 지분을 제시하지 않습니다.

입력 형태
--------
``family_graph`` 는 오케스트레이터가 채워 넣는 dict 입니다.
- 형태 A (기본): ``{"heirs": [{"name", "relation", "alive", "minor"}, ...]}``
  (family_graph.repository.get_heirs_dict 산출).
- 형태 B (레거시): ``{"spouse_alive": bool, "num_children": int}``.

두 형태 모두 받아들이고, 알 수 없으면 ``has_family_data=False`` 로 돌려줍니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Optional

from pydantic import BaseModel, ValidationError

#: 이 모듈이 이해하는 관계. 그 외 값은 무시(형태 검증 실패로 보지 않음).
LEGAL_RELATIONS = frozenset(
    {"spouse", "child", "parent", "grandchild", "sibling", "grandparent"}
)


class UnsupportedFamilyCase(ValueError):
    """현재 family_graph 만으로 안전하게 법정상속인을 확정할 수 없는 경우."""


class HeirInfo(BaseModel):
    """분류 결과에 담기는 상속인 한 명. (계산 로직이 .name/.relation 을 씀)"""

    name: str
    relation: str
    alive: bool = True
    minor: bool = False


@dataclass
class HeirClassification:
    """classify_heirs() 결과.

    ``unsupported_reason`` 이 채워졌으면 ``legal_heirs`` / ``statutory_shares`` 는
    비어 있습니다 — 호출부는 그 이유를 사용자에게 안내하거나
    UnsupportedFamilyCase 로 올려야 합니다.
    """

    #: family_graph 에서 상속인 정보를 읽어낼 수 있었는지.
    has_family_data: bool = False
    spouse_exists: bool = False
    children_count: int = 0
    parents_count: int = 0
    #: 배우자가 생존해 있고 손자녀(대습상속 자리)가 함께 있는지.
    #: tax_calculator 가 "대습상속 지분 계산 미지원" 안내로 분기하는 신호.
    has_grandchild_heir: bool = False
    #: 배우자가 직계비속·직계존속 없이 단독으로 상속하는지.
    spouse_is_sole_heir: bool = False
    legal_heirs: list[HeirInfo] = field(default_factory=list)
    statutory_shares: dict[str, Fraction] = field(default_factory=dict)
    unsupported_reason: Optional[str] = None

    @property
    def ok(self) -> bool:
        """법정상속인·법정상속분을 안전하게 계산했는지."""
        return self.has_family_data and self.unsupported_reason is None


def _read_members(family_graph: Optional[dict[str, Any]]) -> Optional[list[HeirInfo]]:
    """family_graph 를 HeirInfo 목록으로 정규화. 못 읽으면 None."""
    if not isinstance(family_graph, dict):
        return None

    raw = family_graph.get("heirs")
    if isinstance(raw, list) and raw:
        members: list[HeirInfo] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                members.append(HeirInfo.model_validate(item))
            except ValidationError:
                # 이름/관계가 빠진 항목 하나가 전체 분류를 막지 않게 건너뛴다.
                continue
        return members or None

    # 형태 B (레거시 최소 형태)
    spouse_alive = family_graph.get("spouse_alive")
    num_children = family_graph.get("num_children")
    if isinstance(num_children, int):
        members = []
        if spouse_alive:
            members.append(HeirInfo(name="배우자", relation="spouse"))
        for index in range(max(0, num_children)):
            members.append(HeirInfo(name=f"자녀 {index + 1}", relation="child"))
        return members or None

    return None


def _statutory_shares(legal_heirs: list[HeirInfo]) -> dict[str, Fraction]:
    """동순위 1, 배우자 1.5 의 가중치로 법정상속분을 계산한다 (민법 1009조)."""
    has_co_heir = len(legal_heirs) > 1
    weights: dict[str, Fraction] = {}
    for heir in legal_heirs:
        if heir.relation == "spouse" and has_co_heir:
            weights[heir.name] = Fraction(3, 2)
        else:
            weights[heir.name] = Fraction(1, 1)

    total_weight = sum(weights.values(), start=Fraction(0, 1))
    if total_weight == 0:
        return {}
    return {name: weight / total_weight for name, weight in weights.items()}


def classify_heirs(family_graph: Optional[dict[str, Any]]) -> HeirClassification:
    """family_graph 에서 법정상속인과 법정상속분을 계산한다. 절대 예외를 던지지
    않고, 안전하게 판단할 수 없는 경우는 ``unsupported_reason`` 으로 돌려준다."""
    members = _read_members(family_graph)
    if members is None:
        return HeirClassification(has_family_data=False)

    alive = [m for m in members if m.alive]
    result = HeirClassification(has_family_data=True)
    if not alive:
        result.unsupported_reason = "생존 가족 정보가 없어 계산할 수 없습니다."
        return result

    seen: set[str] = set()
    duplicates = {m.name for m in alive if m.name in seen or seen.add(m.name)}
    if duplicates:
        result.unsupported_reason = (
            "동일한 이름의 가족이 있어 상속인을 구분할 수 없습니다: "
            + ", ".join(sorted(duplicates))
        )
        return result

    spouse = [m for m in alive if m.relation == "spouse"]
    children = [m for m in alive if m.relation == "child"]
    parents = [m for m in alive if m.relation == "parent"]
    grandchildren = [m for m in alive if m.relation == "grandchild"]
    grandparents = [m for m in alive if m.relation == "grandparent"]
    siblings = [m for m in alive if m.relation == "sibling"]

    result.spouse_exists = bool(spouse)
    result.children_count = len(children)
    result.parents_count = len(parents)
    result.has_grandchild_heir = bool(spouse) and bool(grandchildren)
    result.spouse_is_sole_heir = bool(spouse) and not (
        children or parents or grandchildren or grandparents
    )

    # ---- 법정상속인 선택 (민법 1000·1003조) ----
    if len(spouse) > 1:
        result.unsupported_reason = (
            "배우자가 두 명 이상으로 입력되어 확인이 필요합니다."
        )
        return result

    if children:
        legal_heirs = spouse + children
    elif grandchildren:
        # 자녀 없이 손자녀만 있으면 어느 자녀의 지분을 대습하는지 그래프로는 모른다.
        result.unsupported_reason = (
            "손자녀가 상속인이 될 수 있는 경우에는 대습상속 관계 확인이 필요합니다."
        )
        return result
    elif parents:
        legal_heirs = spouse + parents
    elif grandparents:
        result.unsupported_reason = (
            "조부모가 상속인이 될 수 있는 경우에는 최근친 직계존속 확인이 필요합니다."
        )
        return result
    elif spouse:
        legal_heirs = list(spouse)
    elif siblings:
        legal_heirs = list(siblings)
    else:
        result.unsupported_reason = (
            "현재 가족관계만으로 법정상속인을 확인할 수 없습니다."
        )
        return result

    result.legal_heirs = legal_heirs
    result.statutory_shares = _statutory_shares(legal_heirs)
    return result


def select_legal_heirs(family_graph: Optional[dict[str, Any]]) -> list[HeirInfo]:
    """classify_heirs 의 얇은 래퍼 — 안전하지 않으면 UnsupportedFamilyCase."""
    classification = classify_heirs(family_graph)
    if not classification.has_family_data:
        raise UnsupportedFamilyCase(
            "가족관계 정보가 없어 법정상속분을 계산할 수 없습니다."
        )
    if classification.unsupported_reason:
        raise UnsupportedFamilyCase(classification.unsupported_reason)
    return classification.legal_heirs


__all__ = [
    "HeirInfo",
    "HeirClassification",
    "UnsupportedFamilyCase",
    "classify_heirs",
    "select_legal_heirs",
    "LEGAL_RELATIONS",
]
