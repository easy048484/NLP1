"""공동상속인 협의 체크리스트.

"이 결정에는 누구의 동의가 필요한가"를 가족관계 그래프에서 계산합니다.
누가 얼마를 가질지는 계산하지 않습니다 (경계 2번).

family_graph의 최종 스키마는 지원님 담당이라 아직 확정 전입니다. 지금은
두 가지 형태를 모두 받아들이고, 모르는 형태면 조용히 비워둡니다.
그래프가 확정되면 _read_heirs만 고치면 됩니다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

_RELATION_LABELS = {
    "spouse": "배우자",
    "child": "자녀",
    "parent": "부모",
    "grandchild": "손자녀",
    "sibling": "형제자매",
    "grandparent": "조부모",
}


class Heir(BaseModel):
    name: str
    relation: str
    relation_label: str
    minor: bool = False


class ConsentChecklist(BaseModel):
    #: 협의서에 서명·날인이 필요한 사람들
    signers: list[Heir]
    #: 상속인 수
    heir_count: int
    #: 미성년 상속인이 있어 특별대리인이 필요할 수 있는지
    needs_special_representative: bool = False
    notes: list[str] = []
    available: bool = True

    @classmethod
    def unavailable(cls) -> "ConsentChecklist":
        return cls(
            signers=[],
            heir_count=0,
            available=False,
            notes=["가족관계 정보가 아직 없어 동의가 필요한 분을 계산하지 못했습니다."],
        )


def _label(relation: str) -> str:
    return _RELATION_LABELS.get(relation, relation or "상속인")


def _read_heirs(family_graph: dict[str, Any] | None) -> list[Heir] | None:
    if not isinstance(family_graph, dict):
        return None

    # 형태 A: 상속인 목록이 그대로 들어오는 경우
    raw = family_graph.get("heirs")
    if isinstance(raw, list) and raw:
        heirs: list[Heir] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            if item.get("alive") is False:
                continue
            relation = str(item.get("relation") or "")
            heirs.append(
                Heir(
                    name=str(item.get("name") or f"상속인 {index + 1}"),
                    relation=relation,
                    relation_label=_label(relation),
                    minor=bool(item.get("minor", False)),
                )
            )
        return heirs or None

    # 형태 B: 현재 family_graph.engine이 쓰는 최소 형태
    spouse_alive = family_graph.get("spouse_alive")
    num_children = family_graph.get("num_children")
    if isinstance(num_children, int):
        heirs = []
        if spouse_alive:
            heirs.append(
                Heir(name="배우자", relation="spouse", relation_label="배우자")
            )
        for index in range(num_children):
            heirs.append(
                Heir(name=f"자녀 {index + 1}", relation="child", relation_label="자녀")
            )
        return heirs or None

    return None


def build_checklist(family_graph: dict[str, Any] | None) -> ConsentChecklist:
    """상속재산분할협의서에 서명이 필요한 사람 목록을 만듭니다."""
    heirs = _read_heirs(family_graph)
    if heirs is None:
        return ConsentChecklist.unavailable()

    minors = [heir for heir in heirs if heir.minor]
    notes = [
        "상속재산분할협의서는 상속인 전원의 서명·날인과 인감증명서가 필요합니다.",
        "한 명이라도 빠지면 협의서 전체가 무효가 됩니다.",
    ]
    if minors:
        notes.append(
            "미성년 상속인이 있고 친권자도 함께 상속인인 경우, 이해가 상충하므로 "
            "가정법원에 특별대리인 선임을 신청해야 할 수 있습니다."
        )
    if len(heirs) == 1:
        notes = ["상속인이 한 분이라 분할협의 절차 자체가 필요하지 않습니다."]

    return ConsentChecklist(
        signers=heirs,
        heir_count=len(heirs),
        needs_special_representative=bool(minors),
        notes=notes,
    )
