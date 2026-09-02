"""FastAPI 진입점. `uvicorn main:app --reload`로 실행합니다."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

import orchestrator
from auth import get_current_user_id_optional
from auth import router as auth_router
from db.base import DatabaseNotConfigured, session_scope
from family_graph import repository as family_graph_repository
from family_graph import router as family_graph_router
from orchestrator import llm_policy, route
from orchestrator.router import current_session_store
from orchestrator.session_store import PostgresSessionStore, session_ttl_seconds
from schemas import AgentInput, ChatResponse

logger = logging.getLogger(__name__)

_parents = Path(__file__).resolve().parents
_env_path = _parents[2] / ".env" if len(_parents) > 2 else None
if _env_path and _env_path.exists():
    load_dotenv(_env_path)

#: 만료 데이터 정리 주기(초). 0 이하면 배치를 아예 띄우지 않습니다.
_PURGE_INTERVAL_SECONDS = int(os.getenv("PURGE_INTERVAL_SECONDS", "900") or 900)


def purge_expired_data() -> tuple[int, int]:
    """만료된 세션과 방치된 익명 가족관계 그래프를 실제로 지웁니다.

    지금까지 만료는 "조회할 때 무시"였을 뿐이라 행 자체는 영구히 남았습니다.
    비로그인 대화의 원문·사망일·재산정보가 계속 쌓인다는 뜻이라, 안 보이게
    하는 것과 지우는 것을 분리하지 않습니다.

    돌려주는 값은 (지운 세션 수, 지운 익명 그래프 수)입니다.
    """
    removed_sessions = current_session_store().purge_expired()

    removed_graphs = 0
    # 익명 그래프는 비로그인 세션과 같은 기준으로 방치 여부를 판단합니다.
    anonymous_ttl = session_ttl_seconds(None)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=anonymous_ttl)
    try:
        with session_scope() as db:
            removed_graphs = family_graph_repository.purge_anonymous_graphs(
                db, older_than=cutoff
            )
    except DatabaseNotConfigured:
        # DB 없이 도는 환경(CI, 로컬 mock)에서는 지울 그래프 자체가 없습니다.
        pass

    return removed_sessions, removed_graphs


async def _purge_loop() -> None:
    while True:
        await asyncio.sleep(_PURGE_INTERVAL_SECONDS)
        try:
            sessions, graphs = await asyncio.to_thread(purge_expired_data)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — 정리 실패가 서버를 죽이면 안 됩니다
            logger.exception("만료 데이터 정리 실패 — 다음 주기에 다시 시도합니다.")
            continue
        if sessions or graphs:
            logger.info(
                "만료 데이터 정리: 세션 %d건, 익명 가족관계 %d건 삭제", sessions, graphs
            )


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    task: Optional[asyncio.Task] = None
    if _PURGE_INTERVAL_SECONDS > 0:
        task = asyncio.create_task(_purge_loop())
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="가족 자산 준비 AI 에이전트 API", lifespan=_lifespan)

_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DATABASE_URL이 있으면 세션 저장소를 Postgres 기반으로 교체합니다. 없는
# 환경(로컬에서 DB 없이 mock만 돌릴 때, 지금 CI)에서는 기본값인
# InMemorySessionStore가 그대로 쓰입니다 — 이 분기 자체가 없어도 동작은
# 이전과 같습니다.
if os.getenv("DATABASE_URL"):
    orchestrator.configure_session_store(PostgresSessionStore())

app.include_router(auth_router)
app.include_router(family_graph_router)


# 데모·운영 환경(ORCHESTRATOR_USE_LLM=required)에서는 키 누락을 기동 시점에
# 시끄럽게 실패시킵니다 — 조용한 규칙 기반 폴백으로 열화된 채 데모하는 사고 방지.
if llm_policy.llm_required() and not os.getenv("ANTHROPIC_API_KEY", "").strip():
    raise RuntimeError(
        "ORCHESTRATOR_USE_LLM=required 인데 ANTHROPIC_API_KEY가 비어 있습니다. "
        "루트 .env 또는 배포 환경변수에 키를 넣으세요."
    )


@app.get("/health")
def health() -> dict[str, str]:
    """llm: "on"(정상) | "off"(플래그로 끔) | "unconfigured"(키 없음 → 폴백 동작 중)."""
    return {"status": "ok", "llm": llm_policy.llm_status()}


@app.post("/chat", response_model=ChatResponse)
def chat(
    payload: AgentInput,
    user_id: Optional[str] = Depends(get_current_user_id_optional),
) -> ChatResponse:
    """대화 한 턴.

    Authorization 헤더는 선택입니다 — 없으면 비로그인 세션(2시간 뒤 삭제),
    있으면 그 계정 세션(30일 보관)으로 동작합니다. 비로그인으로 시작한 대화를
    로그인한 채로 이어가면 그 자리에서 계정에 붙습니다(router.node_load_session).
    """
    return route(payload, user_id=user_id)
