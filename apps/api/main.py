"""FastAPI 진입점. `uvicorn main:app --reload`로 실행합니다."""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from orchestrator import route
from schemas import AgentInput, AgentOutput

# 저장소 루트의 .env를 읽습니다 (README 안내와 동일한 위치: repo-root/.env).
# docker-compose는 env_file로 별도 주입하므로 여기서는 로컬(uvicorn --reload) 실행만 보정합니다.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

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
