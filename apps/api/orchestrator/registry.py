"""
에이전트 레지스트리 (담당: 정민) — 축 1 "에이전트가 스스로를 선언한다".

각 에이전트 패키지(agents/<이름>/)에 spec.py 를 두고 그 안에서 AgentSpec 하나를
모듈 변수 SPEC 으로 선언하면, 오케스트레이터는 이 모듈이 처음 쓰일 때
agents/ 아래를 훑어 자동으로 등록합니다. 오케스트레이터 핵심 코드(router.py /
planner.py)는 에이전트 이름을 하드코딩하지 않습니다.

새 에이전트 붙이는 법
--------------------
1. schemas/agent_io.py 의 AgentName 에 이름을 추가한다 (프론트 types.ts 도 같이).
2. agents/<이름>/spec.py 에 SPEC = AgentSpec(...) 을 선언한다.
3. entrypoint 는 기존과 같은 동기 함수 `run(AgentInput) -> AgentOutput` 이다.
   (병렬 실행은 오케스트레이터가 스레드로 감싸서 처리하므로 에이전트는 async 를
   몰라도 된다 — 결정 4.)
4. requires / produces 는 공통 컨텍스트 필드 이름이다. 같은 턴에 뽑힌 에이전트
   A.produces 와 B.requires 가 겹치면 A → B 순서로 돌고, 안 겹치면 병렬로 돈다.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, ConfigDict, Field

from schemas import AgentAxis, AgentInput, AgentName, AgentOutput

logger = logging.getLogger(__name__)

Entrypoint = Callable[[AgentInput], AgentOutput]


class AgentSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: AgentName
    axes: list[AgentAxis] = Field(
        min_length=1,
        description="담당 상담 축 목록. 양쪽을 담당하면 pre_need와 post_death를 모두 선언",
    )
    description: str = Field(description="라우팅 LLM용 한 줄 설명")
    example_utterances: list[str] = Field(
        default_factory=list, description="few-shot 라우팅 예시 문장"
    )
    keywords: list[str] = Field(default_factory=list, description="빠른 경로용 키워드")
    requires: list[str] = Field(
        default_factory=list, description="필요로 하는 공통 컨텍스트 필드"
    )
    produces: list[str] = Field(
        default_factory=list, description="만들어내는 공통 컨텍스트 필드"
    )
    entrypoint: Entrypoint
    #: 껍데기(stub) 표시. 라우팅 후보로는 편입되지만, 분류 LLM 프롬프트와 프론트
    #: 표시에서 "준비 중"으로 구분합니다.
    is_stub: bool = False


_REGISTRY: dict[AgentName, AgentSpec] = {}
_DISCOVERED = False


def register(spec: AgentSpec) -> AgentSpec:
    """AgentSpec 하나를 등록합니다. 같은 이름이면 나중 것이 덮어씁니다(테스트 편의)."""
    _REGISTRY[spec.name] = spec
    return spec


def _discover() -> None:
    """agents/*/spec.py 를 전부 import 해서 SPEC 을 등록합니다. 한 번만 실행됩니다."""
    global _DISCOVERED
    if _DISCOVERED:
        return
    _DISCOVERED = True
    agents_dir = Path(__file__).resolve().parent.parent / "agents"
    for module_info in pkgutil.iter_modules([str(agents_dir)]):
        if not module_info.ispkg:
            continue
        spec_path = agents_dir / module_info.name / "spec.py"
        if not spec_path.exists():
            continue
        module_name = f"agents.{module_info.name}.spec"
        try:
            module = importlib.import_module(module_name)
        except (
            Exception
        ):  # noqa: BLE001 — 한 에이전트의 import 실패가 전체를 죽이면 안 됨
            logger.exception("에이전트 spec import 실패: %s", module_name)
            continue
        spec = getattr(module, "SPEC", None)
        if isinstance(spec, AgentSpec):
            register(spec)
        else:
            logger.warning("%s 에 SPEC(AgentSpec) 이 없습니다.", module_name)


def all_specs() -> dict[AgentName, AgentSpec]:
    _discover()
    return dict(_REGISTRY)


def get(name: AgentName) -> AgentSpec:
    _discover()
    return _REGISTRY[name]


def get_optional(name: AgentName) -> Optional[AgentSpec]:
    _discover()
    return _REGISTRY.get(name)


def match_keywords(user_message: str) -> list[AgentName]:
    """메시지에 키워드가 등장하는 에이전트를 등록 순서대로 돌려줍니다 (중복 없음)."""
    _discover()
    hits: list[AgentName] = []
    for name, spec in _REGISTRY.items():
        if any(keyword in user_message for keyword in spec.keywords):
            hits.append(name)
    return hits


def reset_for_tests() -> None:
    """테스트 전용: 레지스트리를 비우고 다음 접근 때 다시 discover 하게 합니다."""
    global _DISCOVERED
    _REGISTRY.clear()
    _DISCOVERED = False
