"""FastAPI 진입점. `uvicorn main:app --reload`로 실행합니다."""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from orchestrator import route
from schemas import AgentInput, AgentOutput

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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=AgentOutput)
def chat(payload: AgentInput) -> AgentOutput:
    return route(payload)
