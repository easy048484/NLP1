"""
유언 방식(민법 5방식) 조회 헬퍼.

agent.py 가 이 모듈로 rules/will_types.json 을 조회해서 방식별 분기를 결정한다.
지원 여부·안내 문구·요건 요약을 여기서 하드코딩하지 않고 항상 JSON을 조회한다
(CLAUDE.md 절대 원칙 1 — 판정/분기 근거는 룰 파일에 둔다 — 을 방식 판별에도 적용).
"""

from __future__ import annotations

import json
import re
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


def no_will_guidance() -> dict[str, Any]:
    """ "유언장이 없거나 찾지 못했다" 선택 시 쓸 안내 문구 묶음.

    공정증서 고지 / 법정상속 안내 / 채팅 복귀 안내를 담는다. "unknown"과 마찬가지로
    민법 5방식 중 하나가 아니라 UI sentinel이라 will_types 배열이 아닌 별도 키에 있다.
    """
    return _load()["no_will"]


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


@lru_cache(maxsize=8)
def _compile_patterns(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    """regex 문자열 목록을 컴파일한다. 잘못된 regex(re.error)가 섞여 있어도
    로딩 전체가 죽지 않도록 그 항목만 조용히 건너뛴다 — rules/will_types.json
    은 코드 배포와 분리해 수정될 수 있는 설정 파일이라, 오타 하나가 에이전트
    전체를 죽이면 안 된다(다른 config 파일들과 동일한 안전 처리 원칙).
    lru_cache의 키가 tuple이라 호출부에서 list를 tuple로 바꿔 넘긴다."""
    compiled = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error:
            continue
    return tuple(compiled)


def _any_pattern_matches(patterns: list[str], text: str) -> bool:
    return any(p.search(text) for p in _compile_patterns(tuple(patterns)))


def infer_will_type_from_message(user_message: str) -> Optional[str]:
    """자연어에서 명백한 will_type을 rules/will_types.json 을 generic하게
    순회해 추론한다 — 대상은 민법 5방식(will_types[].inference_markers)과
    no_will sentinel(no_will.inference_markers/inference_patterns) 둘 다다.

    핵심 invariant: 사용자가 민법상 유언 방식을 명백하게 특정했다면, 그
    방식이 full-support(handwritten/recording)인지 guidance-only(notarial/
    secret/oral)인지와 무관하게 방식 선택 질문을 다시 하지 않는다 — support
    (자동 점검 가능 여부)와 inference(방식을 자연어로 알아챌 수 있는지)는
    서로 다른 축이다. 마찬가지로 "유언장이 있는지 확실하지 않아요"처럼
    유언장 존재 자체가 불확실하면 방식부터 묻지 않고 곧장 no_will
    ("none") 경로로 보낸다(2026-09-06) — "어떤 방식인지 모르겠다"(유언장은
    있음, unknown이 답할 질문)와는 다른 축이라 섞이면 안 된다. agent.py 는
    더 이상 방식별/sentinel별 marker 상수를 갖지 않고 이 함수 하나만
    호출한다.

    marker(exact substring)는 각 후보마다 "명백한" 표현만 담아야 한다(예:
    "자필증서"/"공정증서"/"비밀증서"/"구수증서" 같은 법정 방식명 자체,
    "음성메모"처럼 그 방식임이 분명한 구어체 표현) — "서류"/"증서"/"공증"
    처럼 여러 후보에 공통될 수 있는 표현은 넣지 않는다.

    no_will만 추가로 inference_patterns(regex)/exclusion_patterns(regex)를
    쓴다(#150) — "유언장이 없는 건지, 못 찾았는 건지 잘 모르겠어요"처럼
    조사·어미·띄어쓰기가 자유롭게 섞이는 "존재 자체가 불확실함" 표현은
    exact substring marker로 다 나열할 수 없어서다. inference_patterns 중
    하나라도 매치하고 exclusion_patterns가 하나도 매치하지 않으면 "none"
    후보로 추가한다 — exclusion은 "유언장은 있는데"처럼 존재를 이미 확정한
    문구가 함께 있을 때를 위한 defense-in-depth다(정교하게 짠
    inference_patterns 자체는 그런 문장과 안 겹치도록 설계했다). 방식(어떤
    유언인지)에 대한 불확실 표현("어떤 방식인지 모르겠어요" 등)은 "있/없"가
    "유언장" 근처에 붙어 나오지 않아 이 패턴에 걸리지 않는다 — rules/
    will_types.json 의 inference_patterns_note 참고. 컴파일 실패하는 regex는
    조용히 건너뛴다(_compile_patterns).

    충돌 방어: 하나의 메시지가 서로 다른 두 후보의 marker/pattern에 동시에
    걸리면(예: "자필증서인지 공정증서인지 모르겠습니다") 임의로 하나를
    고르지 않고 None을 반환해 기존 방식 선택 질문으로 돌아간다. 정확히
    하나의 후보만 hit일 때만 그 값을 반환한다."""
    matched_ids = {
        wt["id"]
        for wt in _load()["will_types"]
        if any(marker in user_message for marker in wt.get("inference_markers", []))
    }
    no_will = _load()["no_will"]
    no_will_hit = any(
        marker in user_message for marker in no_will.get("inference_markers", [])
    ) or (
        _any_pattern_matches(no_will.get("inference_patterns", []), user_message)
        and not _any_pattern_matches(
            no_will.get("exclusion_patterns", []), user_message
        )
    )
    if no_will_hit:
        matched_ids.add("none")
    if len(matched_ids) == 1:
        return next(iter(matched_ids))
    return None


def infer_will_type_switch_from_message(user_message: str) -> Optional[str]:
    """이미 will_type이 저장된 뒤에도, 이번 턴 자연어에 명백한 "다른 방식으로
    바꾸겠다"는 선택/변경 의도가 있으면 그 새 will_type을 반환한다(2026-09-07).

    실측 재현: handwritten이 저장된 상태에서 "아아 녹음으로 하려고"라고 답해도
    will_type이 None일 때만 자연어를 보던 기존 로직 때문에 계속 handwritten
    가이드가 반복됐다. infer_will_type_from_message()(초기 추론)와는 의도적으로
    분리된 별도 함수다 — "녹음 유언은 자필이랑 뭐가 달라?" 같은 단순 언급/비교
    질문에서 state가 바뀌면 안 되므로, will_types[].switch_markers(방식별
    "명백한 이름" 토큰) 바로 뒤에 rules/will_types.json 의
    type_switch.intent_suffix_pattern(선택/변경을 확정하는 어미: "~로 하려고/
    할게/할래/바꿀게/바꾸려고/하겠습니다" 등)이 곧장 붙어야만 switch로 인정한다.

    switch_markers가 initial inference용 inference_markers와 다른 별도
    필드인 이유: recording의 "녹음"은 단독으로는 "녹음 파일이 있어요"처럼
    오탐 위험이 커 initial inference marker에서 의도적으로 뺐지만(파일/메모와
    혼동), "녹음으로 하려고"처럼 선택 어미가 바로 붙으면 명백한 의도라 switch
    판별에만 한정해 허용한다 — 초기 추론 결과는 이 함수가 건드리지 않는다.

    충돌 방어: 두 후보 이상의 switch 패턴이 동시에 걸리면(사실상 거의 없지만)
    임의로 고르지 않고 None을 반환해 저장된 state.will_type을 그대로 둔다.
    """
    suffix_pattern = _load().get("type_switch", {}).get("intent_suffix_pattern")
    if not suffix_pattern:
        return None
    matched_ids: set[str] = set()
    for wt in _load()["will_types"]:
        for marker in wt.get("switch_markers", []):
            pattern = re.escape(marker) + suffix_pattern
            compiled = _compile_patterns((pattern,))
            if compiled and compiled[0].search(user_message):
                matched_ids.add(wt["id"])
                break
    if len(matched_ids) == 1:
        return next(iter(matched_ids))
    return None
