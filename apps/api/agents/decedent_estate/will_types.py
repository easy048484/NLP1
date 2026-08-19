"""
유언 방식(민법 5방식) 조회 헬퍼.

agent.py 가 이 모듈로 rules/will_types.json 을 조회해서 방식별 분기를 결정한다.
지원 여부·안내 문구·요건 요약을 여기서 하드코딩하지 않고 항상 JSON을 조회한다
(CLAUDE.md 절대 원칙 1 — 판정/분기 근거는 룰 파일에 둔다 — 을 방식 판별에도 적용).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_WILL_TYPES_PATH = Path(__file__).parent / "rules" / "will_types.json"


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    with _WILL_TYPES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def selection_question() -> dict[str, Any]:
    """will_type 미확인 시 물어볼 질문 (질문/선택지/자필증서 유도 문구)."""
    return _load()["selection_question"]


def unknown_default() -> dict[str, Any]:
    """ "그 외·모르겠음" 선택 시 기본으로 삼을 방식과 안내 문구."""
    return _load()["unknown_default"]


def intent_question() -> dict[str, Any]:
    """intent(이용 목적) 값이 잘못 온 경우 재확인할 질문 (review/prepare 선택지).

    will_type이 full 지원(handwritten/recording/unknown)일 때만 의미가 있다 —
    notarial/secret/oral은 애초에 요건 판정을 돌지 않아 review/prepare 구분이
    없다. 값이 아예 없을 때는(agent.py 의 _resolve_intent) 이 질문을 띄우지
    않고 default("review")로 조용히 넘어간다 — 기존 호출부 하위 호환 유지."""
    return _load()["intent_question"]


def get_will_type(will_type_id: str) -> Optional[dict[str, Any]]:
    for wt in _load()["will_types"]:
        if wt["id"] == will_type_id:
            return wt
    return None


def known_will_type_ids() -> tuple[str, ...]:
    """실제 민법상 5방식 id만 (UI의 "unknown" 선택지는 이 방식들 중 하나가 아니라
    별도 sentinel이라 포함하지 않는다)."""
    return tuple(wt["id"] for wt in _load()["will_types"])
