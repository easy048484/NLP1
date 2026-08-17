# 상속인 절차 내비게이터 (담당: 정민)

## 설계 한 줄

**결정론적 절차 엔진 + LLM 껍데기.** 기한·서류·기관은 전부 Python 데이터에서 나오고,
Claude는 입구(자연어 → 슬롯)와 출구(구조체 → 쉬운 말)에만 씁니다.

```
사용자 발화 → [Claude: 슬롯 추출] → [순수 Python: 절차 엔진] → [Claude: 서술] → 답변
                                          ↑ 사실은 여기서만 나옴
```

기한을 LLM이 생성하게 두면 경계를 지키기 이전에 **사실이 틀립니다**. 3개월을 2개월로
말하거나 없는 서류를 지어내는 순간 서비스가 성립하지 않습니다.

## 파일 지도

| 파일 | 역할 | LLM |
| --- | --- | :---: |
| `procedure/steps.py` | 절차 단계 DAG, 기한 개월 수, 근거 조문 | ✗ |
| `procedure/knowledge.py` | 단계별 서류·접수기관·링크 | ✗ |
| `procedure/deadlines.py` | 사망일 기준 기한 역산 (순수 함수) | ✗ |
| `planner.py` | 상태 → "지금 어디, 다음 뭐" 계산 | ✗ |
| `consent.py` | 가족관계 그래프 → 동의 필요자 | ✗ |
| `ics.py` | 기한 → 캘린더(.ics) | ✗ |
| `guardrails.py` | 경계 감지·고정 응답·출력 후검사 | ✗ |
| `state.py` | 대화 슬롯, context 왕복 | ✗ |
| `slots.py` | 발화 → 슬롯 (규칙 기반 + Claude) | ✓ |
| `prompts.py` | 시스템 프롬프트, 사실 블록, 결정론적 렌더러 | ✓ |
| `graph.py` | LangGraph 서브그래프 | — |
| `agent.py` | `run(AgentInput) -> AgentOutput` | — |

## 그래프

```
load → guard ─(경계 위반)→ boundary ────────────┐
         │                                      │
      extract → resolve ─(사망일 없음)→ ask ────┤
                    │                           │
                    └────(충분)────→ compose ───┴→ finalize → END
```

`guard`가 `resolve`보다 **앞**입니다. "한정승인이랑 포기 중에 뭐가 나아요?"는 절차 계산
없이 바로 고정 응답으로 빠집니다.

## 상태 관리

세션 저장소가 아직 없어서 `AgentInput.context["heir_navigator"]` ↔
`AgentOutput.data["heir_navigator"]`로 왕복시킵니다. `schemas/agent_io.py`를 건드리지
않으므로 다른 담당자와 충돌하지 않고, 나중에 DB 세션이 생기면
`state.load_state` / `dump_state`만 갈아끼우면 됩니다.

프론트는 이전 턴의 `data`를 그대로 다음 요청의 `context`로 실어 보내면 됩니다.

## LLM 없이도 동작합니다

`ANTHROPIC_API_KEY`가 없으면 규칙 기반 슬롯 추출 + 결정론적 렌더러로 끝에서 끝까지
동작합니다(개발 원칙 2). CI는 이 경로로 돕니다. 강제로 끄려면
`HEIR_NAVIGATOR_DISABLE_LLM=1`.

## 오케스트레이터 연동 (지원님)

- `heir_navigator.TRIGGER_KEYWORDS` — 라우팅용 키워드. `router.py`를 직접 안 고치려고
  노출해 뒀습니다.
- `AgentOutput.next_action` — `"handoff:tax_calculator"` / `"handoff:decedent_estate"`
  형태의 문자열. 컨벤션 바꾸실 거면 말씀해 주세요.
- `AgentOutput.data["plan"]` — 타임라인·기한·다음 할 일 구조체 (프론트 렌더용)
- `AgentOutput.data["calendar_ics"]` — `.ics` 문자열. 프론트에서 파일로 내려주면
  아이폰·안드로이드 둘 다 캘린더에 들어갑니다.

## 하지 않는 것 (`guardrails.py`가 강제)

1. 한정승인/상속포기 **선택 추천** — 선택지와 결과만 사실대로
2. 구체적 **재산 배분** 개입
3. 가족 **분쟁 중재** — 조정·심판 절차 정보와 전문가 연결만
4. 기한을 **법적 확정**으로 단정 — 모든 기한에 "안내 기준" 문구가 자동으로 붙습니다

## ⚠️ 아직 팀 검증이 필요한 것

`procedure/knowledge.py`의 모든 항목이 `verified=False`입니다. 법령·기관 홈페이지
원문을 대조하고 `verified=True` + `last_verified` 날짜를 채워주세요. 확인 목록:

```python
from agents.heir_navigator.procedure.knowledge import unverified_steps
```

기한 자체(`steps.py`)는 근거 조문을 달아뒀지만, 아래 두 개는 특히 확인이 필요합니다.

- **안심상속 원스톱 신청 기한** (`verified=False`) — 근거 규정과 기산점
- **상속등기 법정 기한** — 현재 "기한 없음"으로 안내 중. 등기 의무화 관련 법 개정이
  있었는지 확인 필요

## 테스트

```bash
cd apps/api && pytest tests/test_heir_navigator.py -q
```

기한 계산(월말 클램프, 윤년, 기산점 분리)에 테스트를 집중했습니다. 여기만 안 깨지면
나머지가 흔들려도 숫자는 틀리지 않습니다.
