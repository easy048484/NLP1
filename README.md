# EZ-NEXT — 가족의 다음을 쉽게 설계하다

**26-2_DSL_Modeling_NLP1**  
15기 이지원 · 15기 김정민 · 16기 이정호 · 16기 전승원

📑 최종 발표자료: [`docs/26_2_NLP1_최종발표자료.pdf`](docs/26_2_NLP1_최종발표자료.pdf)

---

## Project Overview

상속은 누구에게나 갑자기 찾아오지만, 대부분은 처음 겪는 일입니다.  
"아무 신고 없이 석 달 지나면 빚은 안 넘어온다", "고모도 유류분은 받을 수 있다" 같은 말이 친척 단톡방에서 오가지만, 둘 다 틀린 말입니다
(3개월이 지나면 단순승인으로 빚까지 상속되고, 2024년 헌법재판소 결정으로 형제자매의 유류분은 없어졌습니다).

본 프로젝트는 다음 질문에서 출발합니다:

> **재산 규모와 무관하게, 누구나 상속을 정확하고 쉽게 준비하고 처리할 수 있도록 LLM이 도울 수 있는가?**

EZ-NEXT는 **생전과 사후를 잇는** 상속 설계 AI 에이전트 서비스입니다.

| 여정 | 사용자 | 하는 일 |
|---|---|---|
| **생전 — 미리 준비하는 상속** | 부모님 | 재산을 정리하고, 누구에게 얼마를 남길지 설계하고, 유언장과 상속세를 미리 점검 |
| **사후 — 남겨진 절차를 순서대로** | 자녀 | 오늘 할 일과 법정 기한을 받고, 유언장을 점검하고, 각자 몫과 세금을 계산 |

**방법:** 하나의 LLM이 모든 질문에 답하는 대신, LangGraph 오케스트레이터가 질문을 분류해 **5개의 전문 에이전트**에 나눠 맡기고, 결과를 하나의 답변으로 합성합니다.
기한·세율·지분 같은 **사실은 규칙 엔진(코드)이 계산**하고, LLM은 질문 이해와 쉬운 말로 풀어 설명하는 역할만 맡습니다.

---

## Pipeline

### 응답을 만들어내는 구조 (LangGraph StateGraph)

```
 사용자 발화
     │
 load_session ──▶ classify ──▶ build_context ──▶ execute_plan ──▶ compose ──▶ persist_session
  (복원)          (분류)         (준비·계획)        (실행)            (종합)        (저장)
                    │                                 │                 │
           LLM이 필요한 에이전트     의존 순서대로 실행        LLM이 하나로 정리
           선택 (규칙 폴백)        (유언 점검 → 상속세·유류분)   → 코드가 숫자·날짜 대조
                                                            → 불일치 시 원문 그대로
```

| 단계 | 노드 | 역할 |
|---|---|---|
| 복원 | `load_session` | 이전 대화·가족관계·공유 컨텍스트 복원 |
| 분류 | `classify` | LLM 라우팅으로 필요한 에이전트 선택 (키 없으면 키워드 규칙 폴백) |
| 계획 | `build_context` | 에이전트 간 의존(`requires`/`produces`)으로 실행 순서 결정 |
| 실행 | `execute_plan` | 계획 순서대로 에이전트 실행, 결과를 공유 컨텍스트에 기록 |
| 종합 | `compose` | 여러 결과를 LLM이 하나의 답변으로 합성 → 코드가 금액·날짜를 원본과 대조 |
| 저장 | `persist_session` | 세션 상태 저장 (Postgres 또는 인메모리) |

**두 종류의 그래프**
- **비결정 · 오케스트레이터** — LangGraph 6단계가 매 질문마다 어떤 에이전트를 어떤 순서로 부를지 정합니다.
- **결정 · 전문 에이전트** — 같은 입력에는 항상 같은 모양으로 답합니다 (`run(AgentInput) -> AgentOutput` 계약).
- **자동 등록** — 각 에이전트가 `spec.py`에 역할·예시·필요한 정보·만드는 정보를 `AgentSpec`으로 선언하면 오케스트레이터가 자동으로 편입합니다.

### 5개의 전문 에이전트

| # | 에이전트 | 폴더 | 하는 일 |
|---|---|---|---|
| 1 | 자산 정리 | `agents/asset_organizer/` | 흩어진 재산과 빚을 8개 항목 체크리스트로 정리, 누락 항목 질문 |
| 2 | 절차 안내 | `agents/heir_navigator/` | 사망일·진행 상황으로 사망신고~상속세 신고 9단계 정리, 법정 기한 D-day |
| 3 | 유언 점검 | `agents/decedent_estate/` | 민법상 5가지 유언 방식의 요건을 4단계 신호등으로 판정 (사진 업로드 지원) |
| 4 | 유류분 분석 | `agents/heir_share_analyzer/` | 가족 구성과 나눌 비율로 법정상속분·유류분 계산, 부족분 경고 |
| 5 | 상속세 시산 | `agents/tax_calculator/` | 공제·세율을 단계별로 적용한 예상 상속세 계산 |

> `agents/retirement_planner/`(노후 설계)는 구현돼 있으나 서비스 방향을 상속으로 좁히면서 데모에서 제외했습니다.

### 답변 가드레일

| 원칙 | 방법 |
|---|---|
| 법률 판단은 하지 않습니다 | 한정승인·포기처럼 판단이 필요한 질문은 계산하지 않고 전문가 상담으로 안내 |
| 사실은 규칙에서만 | 기한·서류·세액은 규칙 엔진이 계산하고, LLM은 질문 이해와 쉬운 설명만 담당 |
| 한 번 들은 정보는 다시 묻지 않습니다 | 재산·유언장 판정·가족관계를 모든 에이전트가 공유 |
| 민감한 정보는 남기지 않습니다 | 유언장은 판정 요약만 저장, 원문·사진은 폐기. 주민번호·계좌·전화번호는 마스킹 |

### 서비스

- **모바일 사이트** (`/m`) — 부모님용 상속 설계 · 자녀용 사망 후 절차. 버튼 중심 흐름
- **PC 사이트** — 채팅 + 체크리스트·일정·현황 3단 화면
- 모바일과 PC가 같은 에이전트를 쓰기 때문에, 어디서 시작한 상담이든 그대로 이어집니다.

---

## Output / Evaluation

실제 답변 58턴(골든셋)을 대상으로 **코드로 판정할 수 있는 것은 코드로, 나머지는 AI 심사(근거 인용 필수)로** 채점했습니다.

### 라우팅 정확도 (`apps/api/evals/routing/`)

| 지표 | 결과 |
|---|:---:|
| 정확도 (pass / 전체 턴) | **58 / 58 = 100.0%** |

| 에이전트 | precision | recall |
|---|:---:|:---:|
| 자산 정리 | 100.0% | 100.0% |
| 절차 안내 | 100.0% | 100.0% |
| 유언 점검 | 100.0% | 100.0% |
| 유류분 분석 | 100.0% | 100.0% |
| 상속세 시산 | 100.0% | 100.0% |

### 답변 품질 (`apps/api/evals/quality/`)

| 기준 | 정의 | 방식 | 결과 |
|---|---|---|:---:|
| **① 정확성** | 답변 속 모든 숫자(날짜·금액·퍼센트)가 출처(사용자 발화·코드 계산값·법정 상수)로 추적되는가 | 코드 대조 | **100%** (58턴, 수치 85건) |
| **② 경계 준수** | 해서는 안 될 말(추천·단정·개인정보 노출)이 없는가 | 코드 규칙 + AI 심사 | **94.8%** |
| **③ 톤** | 존댓말·쉬운 말·상황 적합·문장 구조 4개 차원 모두 3점 이상 | AI 심사 + 코드 | **53.4%** |

- LLM이 생성한 본 답변(20턴)만 보면 톤 통과율 **95.0%** — 낮은 점수는 주로 정보를 묻는 초기 인테이크 응답의 고정 문구에서 나왔습니다.
- 세부 리포트: [`apps/api/evals/quality/results/`](apps/api/evals/quality/results/), [`apps/api/evals/routing/results/`](apps/api/evals/routing/results/)

### 한계와 향후 방향

| 한계 | 향후 방향 |
|---|---|
| **법령 개정 반영** — 세율·공제액·기한 등 계산 기준은 법령 개정 시 개발자가 코드에 직접 반영 | 공식 API로 개정 사항을 정기 확인, 시행일별 규칙 버전 관리 |
| **복합 질문 처리** — 담당 범위가 겹치는 질문에서 에이전트 선택·실행 순서가 불안정 | 골든셋으로 에이전트 선택·실행 순서 검증, 코드 변경 시 자동 재채점 |
| **법적 판단의 경계** — 수치 일관성은 검증 가능하나 법적 전제·예외 조건·적용 시점 판단은 불가 | 재산·가족·절차 정보를 정리한 전문가 제출용 보고서로 법적 판단은 전문가에게 연계 |

---

## Repository Structure

```
NLP1/
├── apps/
│   ├── api/                         # FastAPI + LangGraph 백엔드
│   │   ├── main.py
│   │   ├── orchestrator/            # 복원→분류→계획→실행→종합→저장 파이프라인
│   │   │   ├── router.py            #   LangGraph StateGraph 정의
│   │   │   ├── planner.py           #   LLM 라우팅 + 규칙 폴백
│   │   │   ├── registry.py          #   AgentSpec 자동 등록
│   │   │   ├── compose.py           #   답변 합성 + 숫자 대조
│   │   │   └── session_store.py     #   세션 저장 (Postgres / 인메모리)
│   │   ├── agents/
│   │   │   ├── asset_organizer/     # 1. 자산 정리
│   │   │   ├── heir_navigator/      # 2. 절차 안내
│   │   │   ├── decedent_estate/     # 3. 유언 점검
│   │   │   ├── heir_share_analyzer/ # 4. 유류분 분석
│   │   │   ├── tax_calculator/      # 5. 상속세 시산
│   │   │   └── retirement_planner/  # (데모 제외) 노후 설계
│   │   ├── family_graph/            # 가족관계 그래프 엔진 (법정상속인 판정)
│   │   ├── schemas/agent_io.py      # AgentInput / AgentOutput 공통 계약
│   │   ├── auth/                    # 회원가입·로그인 (JWT)
│   │   ├── llm/                     # Claude API 클라이언트
│   │   ├── evals/
│   │   │   ├── routing/             # 라우팅 골든셋 + 채점 결과
│   │   │   └── quality/             # 답변 품질 골든셋 + 채점 결과
│   │   ├── alembic/                 # DB 마이그레이션
│   │   └── tests/                   # pytest
│   └── web/                         # React + TypeScript (Vite) 프론트엔드
│       └── src/
│           ├── screens/             # PC 화면
│           ├── mobile/              # 모바일 사이트 (/m)
│           ├── components/
│           └── lib/                 # API 클라이언트·응답 파서
├── docs/                            # 개발 과정 기록 (시나리오·실험설계서 등) + 최종 발표자료
├── infra/                           # Dockerfile, docker-compose
└── .github/workflows/ci.yml         # CI (프론트 lint·test·build / 백엔드 pytest)
```

### Usage

```bash
# 0. 환경 변수 (저장소 루트)
cp .env.example .env        # ANTHROPIC_API_KEY 입력. 비우면 규칙 기반 폴백으로 동작

# 1. 백엔드
cd apps/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload   # DATABASE_URL이 비어 있으면 인메모리 세션

# 2. 프론트엔드
cd apps/web
npm install
npm run dev                 # http://localhost:5173

# (선택) DB까지 한 번에
docker compose -f infra/docker-compose.yml up
```

```bash
# 평가 재실행
cd apps/api
python -m evals.routing.run      # 라우팅 정확도
python -m evals.quality.score evals/routing/results/<결과>.json   # 답변 품질 (라우팅 실행 결과를 입력으로)
```

### Requirements

```
# Backend (Python 3.11)
fastapi
langgraph
anthropic
sqlalchemy
alembic
psycopg2-binary
PyJWT
pytest

# Frontend (Node 20)
react
react-router-dom
typescript
vite
vitest
```

---

## References

- 민법 제1000조~제1118조 (상속·유언·유류분), 상속세 및 증여세법
- 헌법재판소 2024. 4. 25. 선고 2020헌가4 등 결정 (형제자매 유류분 위헌)
- LangGraph. [[docs]](https://langchain-ai.github.io/langgraph/)
- Anthropic Claude API. [[docs]](https://docs.anthropic.com/)
- Zheng, L., et al. (2023). **Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena**. *NeurIPS 2023 Datasets and Benchmarks*. [[paper]](https://arxiv.org/abs/2306.05685)
