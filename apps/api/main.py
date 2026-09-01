"""FastAPI 진입점. `uvicorn main:app --reload`로 실행합니다."""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import orchestrator
from auth import router as auth_router
from family_graph import router as family_graph_router
from orchestrator import llm_policy, route
from orchestrator.session_store import PostgresSessionStore
from schemas import AgentInput, ChatResponse

_parents = Path(__file__).resolve().parents
_env_path = _parents[2] / ".env" if len(_parents) > 2 else None
if _env_path and _env_path.exists():
    load_dotenv(_env_path)

app = FastAPI(title="가족 자산 준비 AI 에이전트 API")

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
def chat(payload: AgentInput) -> ChatResponse:
    return route(payload)
