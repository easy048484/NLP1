# 가족 자산 준비 AI 에이전트

가족 간 자산을 어떻게 물려주고 물려받을지, 재산 규모와 무관하게 누구나 쉽게 준비할 수 있도록 돕는 AI 에이전트 오케스트레이션 서비스입니다.

전체 개발/배포 파이프라인 계획은 [`docs/개발_배포_파이프라인_계획.md`](./docs/개발_배포_파이프라인_계획.md)를 참고하세요.

## 저장소 구조

```
apps/
  web/       # React 프론트엔드 (모바일 웹)
  api/       # FastAPI + LangGraph 오케스트레이터
    orchestrator/   # 라우팅·상태관리·전환
    agents/          # 상속인 절차 내비게이터 / 피상속인 유언장·자산정리 / 상속세 계산
    family_graph/    # 가족관계 그래프 엔진 (공통모듈)
    schemas/         # AgentInput/AgentOutput 등 공통 계약
infra/       # docker-compose, Dockerfile
.github/workflows/   # CI 파이프라인
```

## 로컬 개발 시작하기

### 0. `.env` 만들기 (최초 1회, 저장소 루트에서)

```bash
cp .env.example .env
```

`docker compose`는 이 파일이 없어도 mock API 자체는 기동되지만(값이 비어 있을 뿐), Claude API 키가 필요한 로직을 테스트하려면 미리 채워두는 게 좋습니다.

### 백엔드 (FastAPI)

```bash
cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

`.env`에 `DATABASE_URL`을 채워 세션/가족관계 저장을 Postgres로 쓰려면, 서버를
띄우기 전에 한 번 마이그레이션을 적용해야 합니다.

```bash
alembic upgrade head
```

(DATABASE_URL이 비어 있으면 세션은 그냥 인메모리로 동작하고, 이 단계는
필요 없습니다.)

또는 DB까지 함께 띄우려면 루트에서:

```bash
docker compose -f infra/docker-compose.yml up
```

이 경우 컨테이너가 시작할 때 `alembic upgrade head`를 자동으로 실행하므로
따로 마이그레이션을 적용할 필요가 없습니다 (`infra/Dockerfile.api`의 CMD
참고).

### 프론트엔드 (React)

```bash
cd apps/web
npm install
npm run dev
```

## 브랜치 전략

- `main` — 항상 배포 가능한 상태. push/머지 시 프로덕션에 자동 배포됩니다.
- `develop` — 팀 통합 브랜치. `feature/*` 작업이 여기로 먼저 모입니다.
- `feature/*` — 담당자·기능 단위 작업 브랜치.

자세한 내용은 `docs/개발_배포_파이프라인_계획.md`의 "브랜치 전략" 절을 참고하세요.

## 병렬 개발 시 충돌 지점

에이전트별 폴더(`agents/<name>/`)는 서로 건드리지 않으므로 담당자 간 코드 충돌은 거의 없습니다. 다만 아래 파일들은 여러 명이 같은 파일을 고치게 되므로, PR을 자주 작게 올리고 충돌이 나면 상대방과 먼저 채팅으로 맞춰보고 머지하세요.

- `apps/api/requirements.txt` — 자기 에이전트 로직에 필요한 패키지를 추가할 때 여기를 같이 건드리게 됩니다.
- `apps/api/schemas/agent_io.py` — `AgentInput`/`AgentOutput` 자체를 바꿔야 하면(새 필드 추가 등) PR 설명에 꼭 이유를 적고, 다른 담당자에게 리뷰를 요청하세요. CI의 schema check job이 이 파일 변경 시 자동으로 알려줍니다.
- `apps/api/orchestrator/router.py` — 라우팅 로직은 지원님 담당이니, 새 키워드/에이전트 추가가 필요하면 직접 고치지 말고 요청해주세요.

각 에이전트는 `apps/api/tests/test_agents.py`에서 `run(AgentInput) -> AgentOutput` 계약을 지키는지 CI로 검증합니다. 로직을 mock에서 실제 구현으로 바꿀 때 이 테스트가 깨지면 병합 전에 바로 알 수 있습니다.

## 개발 원칙

1. 뼈대 먼저, 살은 나중에 — 오케스트레이터+mock 에이전트로 끝에서 끝까지 먼저 작동시키고, 이후 진짜 로직으로 하나씩 교체
2. 항상 실행 가능한 상태 유지 — 기능이 없어도 되지만, 있는 기능은 항상 작동
3. 계약(스키마)은 코드보다 먼저 — AgentInput/AgentOutput 표준 입출력 규격을 먼저 정하고 각자 자유롭게 구현
4. 하나의 task 단위로 pr.. 본인도 이해하고 나서 pr.. 나 하나하나 보기 어려워
