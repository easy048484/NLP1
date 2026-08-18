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

## 전체에서의 위치

```
프론트 챗봇 → POST /chat (main.py) → orchestrator/router.py
                                        ├─ "유언"·"자산정리" → decedent_estate
                                        ├─ "상속세"·"세금"   → tax_calculator
                                        └─ 그 외 전부 (기본값) → heir_navigator ★
```

현재 라우터는 키워드 기반 mock이고, 이 에이전트가 **기본 응답자**입니다. 전체 앱
레벨의 LangGraph는 아직 없으며, LangGraph는 이 에이전트 **내부의 서브그래프**
(`graph.py`)로만 존재합니다. 서버는 무상태라서 매 채팅 턴마다
`라우팅 → run() → 그래프 1회 실행 → 응답` 이 반복됩니다.

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

---

## 파일별 설명

각 파일을 같은 형식으로 설명합니다:
**① 역할 / ② 기능 / ③ 어디서 뭘 받아 트리거되는지 / ④ 어떻게 수행하는지 / ⑤ 결과물(예시) / ⑥ 결과물의 행선지**

호출 흐름 순서대로 배치했습니다: 요청이 들어오는 순서 = 읽는 순서입니다.

### `agent.py` — 외부 계약 (진입점)

**① 역할** — 에이전트의 공식 출입구. 오케스트레이터와 맺은 계약
`run(AgentInput) -> AgentOutput`을 이행하는 어댑터입니다. 내부가 LangGraph든 뭐든
바깥에서는 이 함수 하나만 보입니다.

**② 기능** — (a) 이전 턴 상태 복원과 이번 턴 상태 직렬화로 **멀티턴을 성립**시키고,
(b) LLM 사용 가능 여부를 판정하고(`_use_llm`), (c) 테스트에서 오늘 날짜를 고정할 수
있게 하고(`_today`), (d) 그래프가 죽어도 안전 응답을 보장합니다.

**③ 트리거** — `orchestrator/router.py`의 `route()`가 키워드 미매치 시(기본 에이전트)
`heir_navigator.run(payload)`를 호출합니다. 받는 것은 `AgentInput` 하나:
`user_message`(이번 발화), `session_id`, `family_graph`, `context`(**프론트가 되돌려준
이전 턴 상태** 포함).

**④ 수행 방식** —
1. `state.load_state(payload.context)`로 `context["heir_navigator"]`에서 `HeirState` 복원
   (없거나 깨졌으면 빈 상태로 새 출발)
2. 그래프 입력 dict 조립: 발화·가족그래프·오늘 날짜·`use_llm` 플래그·복원된 상태
3. `graph.compiled().invoke(...)` 실행
4. 결과의 `data`에 `dump_state(갱신된 상태)`를 `"heir_navigator"` 키로 첨부
5. 그래프에서 예외가 나면 핵심 기한 2개(3개월·6개월)를 담은 고정 안내로 폴백

**⑤ 결과물** — `AgentOutput`. 예시:

```json
{
  "agent": "heir_navigator",
  "reply": "**곧 다가오는 기한**\n- 한정승인·상속포기 신고 기한: 2026-08-03 (17일 남음)\n...",
  "next_action": "handoff:tax_calculator",
  "data": {
    "plan": { "...": "타임라인·기한·다음 할 일 구조체" },
    "calendar_ics": "BEGIN:VCALENDAR\r\n...",
    "heir_navigator": { "death_date": "2026-05-03", "completed": ["death_report"], "turns": 3 }
  }
}
```

**⑥ 행선지** — `router.route()`의 반환값이 되어 FastAPI `/chat` 응답으로 프론트에
갑니다. 이 중 `data["heir_navigator"]`는 프론트가 **다음 요청의 `context`에 그대로
실어 되돌려 보내야** 하는 몫입니다 (아래 "상태 관리" 참고).

### `graph.py` — LangGraph 서브그래프 (배선도)

**① 역할** — 부품 모듈들을 노드로 조립하고 실행 순서·분기를 결정하는 배선도.
이 에이전트에서 유일하게 LangGraph 프레임워크에 의존하는 파일이며, heir_navigator
전용입니다 (다른 에이전트와 공유하지 않습니다).

**② 기능** — 8개 노드(load/guard/boundary/extract/resolve/ask/compose/finalize)와
2개 조건 분기(`_after_guard`, `_after_resolve`) 정의, 컴파일된 그래프 싱글턴
(`compiled()`), 라우팅용 `TRIGGER_KEYWORDS` 노출. 자체 로직은 거의 없고 각 노드는
다른 모듈 함수를 부르는 한두 줄입니다.

**③ 트리거** — `agent.py`의 `run()`이 `compiled().invoke(graph_input)`으로 실행합니다.
받는 것은 `GraphState` dict: 발화, 가족그래프, 오늘 날짜, `use_llm`, 복원된 `HeirState`.

**④ 수행 방식** — 노드가 순서대로 돌며 각자 바뀐 키만 반환하고 LangGraph가 상태에
병합합니다:
- `load` — 턴 수 +1
- `guard` — `guardrails.check_input()`. 걸리면 `boundary`로 가서 **LLM 없이** 고정
  응답으로 종료
- `extract` — `slots.extract_slots()` 결과를 `HeirState.merge()`
- `resolve` — `planner.build_plan()`으로 절차 계산
- `ask` — 사망일이 없으면 되묻기 (물은 슬롯을 `asked`에 기록해 반복 방지)
- `compose` — `prompts.facts_block()`을 Claude에 넘겨 서술. 실패 시
  `deterministic_reply()` 폴백, 출력 후검사 위반 시 가드레일 템플릿으로 교체,
  디스클레이머 누락 시 강제 부착
- `finalize` — `plan`·`.ics`를 `data`에 담고 handoff 판정. 생전 준비 신호
  (`_PRE_PLANNING`)가 보이고 사망일이 없으면 `handoff:decedent_estate` 역전환

**⑤ 결과물** — 최종 `GraphState`. 핵심 키: `reply`(답변 텍스트),
`next_action`(`"handoff:..."` 또는 None), `data`(`plan`, `calendar_ics`,
`asked_slot`, `boundary` 등), `heir`(갱신된 상태). 예시:

```python
{"reply": "안내를 드리려면 먼저 여쭐 게 있습니다. **돌아가신 날짜**가...",
 "heir": HeirState(turns=1, asked={"death_date"}), "data": {"asked_slot": "death_date"}}
```

**⑥ 행선지** — `agent.py`로 반환되어 `AgentOutput`으로 포장됩니다.

### `state.py` — 대화 기억의 구조와 직렬화

**① 역할** — 멀티턴 대화에서 "지금까지 알아낸 것"을 담는 데이터 구조와, 그것을
JSON으로 왕복시키는 직렬화 계층.

**② 기능** — `HeirState`(누적 슬롯: 사망일, 안 날, 완료 단계, 채무·유언 여부, 협의
상태, 물어본 질문, 턴 수), `SlotUpdate`(한 턴의 추출값), 병합 규칙(`merge`), 질문
전략(`blocking_slot`, `missing_required`), 직렬화(`load_state`/`dump_state`).

**③ 트리거** — 세 곳에서 씁니다. `agent.py`가 턴 시작·끝에 `load_state`/`dump_state`를,
`graph.py`의 `extract` 노드가 `merge`를, `planner.py`가 `blocking_slot`/
`missing_required`를 호출합니다. 받는 것: `context` dict 또는 `SlotUpdate`.

**④ 수행 방식** — pydantic 검증으로 이상한 입력을 걸러내고(깨진 상태면 대화를 깨는
대신 새로 시작), JSON 왕복 시 list로 변한 set을 되살립니다. `merge`는 새 값만
덮어쓰고 None/unknown은 기존 값을 지우지 않습니다. `missing_required`는 시점 규칙을
적용합니다 — 예: 채무 여부는 재산조회를 마친 뒤에만 묻습니다(조회 전엔 사용자가 답할
수 없으므로). `blocking_slot`은 사망일 하나뿐입니다 — 질문 세 개를 연달아 던지면
경황 없는 사용자는 이탈합니다.

**⑤ 결과물** — 복원된 `HeirState` 객체 / 직렬화된 dict. 예시:

```json
{"death_date": "2026-05-03", "known_date": null,
 "completed": ["death_report", "one_stop"], "has_debt": "yes",
 "will_exists": "unknown", "agreement": "none",
 "asked": ["death_date", "progress"], "turns": 4}
```

**⑥ 행선지** — `dump_state` 결과는 `AgentOutput.data["heir_navigator"]`로 프론트에
나가고, 프론트가 다음 요청 `context`로 되돌려주면 `load_state`가 다시 받습니다.
세션 DB가 생기면 이 두 함수만 갈아끼우면 됩니다.

### `slots.py` — 입구 번역기 (발화 → 슬롯)

**① 역할** — 자연어 발화에서 구조화된 정보를 뽑는 입구. LLM이 쓰이는 두 지점 중
하나입니다.

**② 기능** — 규칙 기반 추출(`rule_based`), Claude 추출(`llm_based`), 두 결과의 병합
(`_merge_updates`), 외부 진입점 `extract_slots()`.

**③ 트리거** — `graph.py`의 `extract` 노드가
`extract_slots(user_message, today=..., use_llm=...)`로 호출합니다. 받는 것: 이번 턴
발화 문자열 하나.

**④ 수행 방식** — 2단 구성:
1. **규칙 기반** — 명시적 날짜(`2026년 5월 3일`)와 뚜렷한 완료 표현("사망신고
   했어요")을 정규식으로. 날짜가 여러 개면 애매하므로 손대지 않고 LLM/되묻기에
   맡깁니다.
2. **Claude** — "작년 이맘때쯤", "장례는 치렀고 아직 아무것도 못 했어요" 같은 표현.
   `record_heir_slots` **도구 호출을 강제**해 dict로 받고 pydantic으로 검증합니다.
   시스템 프롬프트가 "근거 없는 값은 null로 두라"를 강제합니다.

병합은 규칙 기반 우선, 빈 자리만 LLM으로 채웁니다. LLM 실패 시 조용히 규칙 기반만
쓰되 지어낸 값은 채우지 않습니다.

**⑤ 결과물** — `SlotUpdate`. 예: 입력 *"아버지가 2026년 5월 3일에 돌아가셨고
사망신고는 했어요. 빚이 좀 있어요"* →

```python
SlotUpdate(death_date=date(2026, 5, 3),
           completed_steps=[StepId.DEATH_REPORT], has_debt="yes")
```

**⑥ 행선지** — `extract` 노드가 `HeirState.merge()`에 넣어 누적 상태를 갱신합니다.

### `guardrails.py` — 경계를 코드로 강제

**① 역할** — "하지 않는 것" 4가지를 프롬프트가 아니라 코드로 막는 안전장치.
프롬프트에 "추천하지 마세요"라고만 써두면 서너 턴 뒤에 샙니다.

**② 기능** — 입력 감지(`check_input`), 출력 후검사(`check_output`), 단정 표현 감지
(`has_overclaim`), 경계별 고정 응답 템플릿(`fallback_reply`).

**③ 트리거** — 두 시점에 불립니다. `guard` 노드가 **사용자 발화**로 `check_input`을
(resolve보다 앞 — 절차 계산 없이 빠져야 하므로), `compose` 노드가 **Claude가 생성한
답변**으로 `check_output`을 호출합니다.

**④ 수행 방식** — 정규식 2중 매칭. 선택 추천은 주제어(`한정승인|상속포기|...`)와
**선택 요구 신호**(`뭐가 나아|추천|골라|...`)가 **둘 다** 있어야 걸립니다 —
"한정승인이 뭐예요?" 같은 설명 요청은 통과시키기 위해서입니다. 걸리면 "답을 못
한다"가 아니라 "**다른 방식으로 답한다**": 고정 템플릿이 선택지와 각각의 결과를
사실대로 전부 제공하고 전문가 연결(법률구조공단 132)로 마무리합니다.

**⑤ 결과물** — `GuardrailHit(boundary, matched, reply)` 또는 None. 예: 입력
*"한정승인이랑 포기 중에 뭐가 나아요?"* →

```python
GuardrailHit(boundary=Boundary.CHOICE_RECOMMENDATION,
             reply="어떤 쪽을 선택해야 하는지는 안내드릴 수 없습니다. ...(선택지 3개 사실 설명)...")
```

**⑥ 행선지** — 입력 감지 결과는 `boundary` 노드가 그대로 최종 `reply`로 씁니다.
출력 후검사 결과는 `compose` 노드가 Claude 답변을 버리고 템플릿으로 교체하는 데
씁니다.

### `planner.py` — 절차 엔진의 심장

**① 역할** — 이 에이전트의 **사실 원천**. 상태를 넣으면 "지금 어디이고 다음에 뭘
해야 하는지"가 나옵니다. LLM 호출 없음, 네트워크 없음, 순수 계산.

**② 기능** — 타임라인 계산(`_timeline`), 다음 할 일 목록(`_next_actions`), 기한
3분류(전체/임박/지남), 채무 시 선택지 제시, handoff 판정(`_handoff`), 되물을 슬롯
결정. 전부 `build_plan()` 하나로 묶입니다.

**③ 트리거** — `graph.py`의 `resolve` 노드가
`build_plan(heir_state, family_graph=..., today=...)`로 호출합니다. 받는 것: 누적
상태(`HeirState`), 가족관계 그래프, 오늘 날짜.

**④ 수행 방식** — `procedure/`의 정적 데이터를 상태와 대조합니다:
`compute_deadlines()`로 기한 역산 → 30일 이내는 `urgent`, 지난 것은 `overdue` 분류
→ `unlocked()`로 지금 할 수 있는 단계를 뽑아 `knowledge.py`의 서류·기관을 붙이고
기한 임박 순 정렬 → `has_debt=="yes"`이고 승인/포기 결정 전이면 선택지 3개 첨부
(추천 없이 결과만) → 재산조회 완료면 `tax_calculator`, 유언장 확인이면
`decedent_estate` handoff 힌트 → `build_checklist()`로 동의 필요자 계산.

**⑤ 결과물** — `ProcedurePlan`. 예시(요약):

```python
ProcedurePlan(
  death_date=date(2026, 5, 3), known_date_estimated=True,
  urgent=[DeadlineItem(label="한정승인·상속포기 신고 기한", due_date=date(2026, 8, 3),
                       days_left=17, law="민법 제1019조 제1항", base_estimated=True)],
  next_actions=[NextAction(title="재산 조회 결과 확인", ...)],
  branches=[Branch(title="한정승인", effect="물려받은 재산 범위 안에서만...")],
  handoff=None, blocking_slot=None, follow_up="will_exists")
```

**⑥ 행선지** — `resolve` 이후의 모든 노드가 소비합니다: `ask`(blocking_slot),
`compose`(사실 블록의 원료), `finalize`(`data["plan"]`으로 직렬화되어 프론트 렌더용,
기한은 `.ics`로).

### `procedure/steps.py` — 절차 단계 DAG (사실 계층)

**① 역할** — 절차 구조의 원천. **에이전트가 내놓는 모든 숫자(기한 개월 수)와 근거
조문의 출처**입니다. LLM은 이 값을 말로 풀기만 하고 스스로 만들지 않습니다.

**② 기능** — 9개 단계(`StepId`: 사망신고 → 안심상속 원스톱 → 재산조회 → 유언확인 →
승인/포기 결정 → 분할협의 → 등기 → 취득세 → 상속세)를 **선행조건 DAG**로 정의.
선형 리스트가 아닌 이유: 안심상속은 사망신고와 병렬 진행이 가능하고, 한정승인
3개월 시계는 재산조회를 기다리는 동안에도 흐릅니다 — 이 병렬성이 사용자가 가장 많이
다치는 지점입니다. `unlocked()`(지금 할 수 있는 단계), `blocked_by()`(막고 있는 선행
단계) 유틸 포함.

**③ 트리거** — 코드가 아니라 **데이터**입니다. import 시점에 상수로 로드되고,
`planner.py`와 `deadlines.py`가 읽습니다.

**④ 수행 방식** — 각 `Step`은 선행조건(`requires`), 기한(`Deadline`: 기산점
`DeadlineBase` + 개월 수 + 근거 조문 + 검증 플래그), 타 에이전트 인계 지점
(`handoff`), 발화 매칭용 별칭(`aliases`)을 가진 불변(frozen) dataclass입니다.
기산점이 분리된 이유: 한정승인·상속포기는 '상속개시 있음을 안 날'(민법 §1019①),
상속세·취득세는 '사망일이 속한 달의 말일'로 절차마다 다릅니다.

**⑤ 결과물** — 정적 튜플 `STEPS`. 예:

```python
Step(id=StepId.ACCEPT_DECIDE, title="단순승인 / 한정승인 / 상속포기 결정",
     deadline=Deadline(base=DeadlineBase.KNOWN, months=3,
                       label="한정승인·상속포기 신고 기한", law="민법 제1019조 제1항"))
```

**⑥ 행선지** — `deadlines.py`(기한 역산의 입력), `planner.py`(타임라인·다음 할 일),
`slots.py`(`StepId` enum을 완료 단계 추출에 사용).

### `procedure/knowledge.py` — 서류·기관 지식베이스 (사실 계층)

**① 역할** — 단계별 필요 서류·접수기관·공식 링크·팁의 출처. RAG 대신 하드코딩 —
항목이 20개 미만이라 검색 정확도보다 "틀리면 바로 고치고, 무엇이 검증됐는지 눈으로
확인된다"가 더 중요합니다.

**② 기능** — `StepGuide` dict(`GUIDES`), 조회 함수 `guide_for(step_id)`, 미검증 목록
`unverified_steps()`.

**③ 트리거** — `planner.py`의 `_next_actions()`가 할 수 있는 단계마다
`guide_for()`를 호출합니다. `unverified_steps()`는 CI/리뷰용입니다.

**④ 수행 방식** — 단순 dict 조회. 각 항목의 `verified`/`last_verified`는 장식이
아닙니다 — `verified=False`면 안내문에 "확인 필요" 표시가 자동으로 붙습니다.

**⑤ 결과물** — `StepGuide`. 예:

```python
StepGuide(step=StepId.ACCEPT_DECIDE,
          documents=("상속포기 또는 한정승인 심판청구서", "사망자의 기본증명서...", ...),
          agencies=("피상속인의 최후 주소지 관할 가정법원",),
          links=(("대한민국 법원 전자민원센터", "https://help.scourt.go.kr"),),
          verified=False)
```

**⑥ 행선지** — `NextAction`의 서류·기관·링크 필드로 들어가 사실 블록과 최종 답변,
`data["plan"]`에 실립니다.

### `procedure/deadlines.py` — 기한 역산 (사실 계층, 순수 함수)

**① 역할** — **에이전트가 내놓는 모든 날짜의 유일한 출처.** LLM도, 네트워크도, 전역
상태도 없습니다. 여기만 테스트가 있으면 나머지가 흔들려도 숫자는 틀리지 않습니다.

**② 기능** — 월 가산(`add_months`), 월말 계산(`month_end`), 단계별 기한 계산
(`deadline_for`), 전체 기한 역산(`compute_deadlines`), 공통 디스클레이머(`DISCLAIMER`).

**③ 트리거** — `planner.build_plan()`이 `compute_deadlines(death_date, known_date,
completed, today)`로 호출합니다. **사망일을 모르면 빈 리스트** — 이 에이전트가
사망일부터 묻는 이유입니다.

**④ 수행 방식** — 민법 §157(초일불산입)·§160(역에 의한 계산)을 따릅니다. 응당일이
없는 달이면 말일로 내리고(§160③ — 예: 1/31 + 1개월 = 2/28), 말일이 토요일·공휴일이면
다음 날 만료(§161)인데 공휴일 달력은 들고 있지 않으므로 계산 대신 안내 문구로
붙입니다. '안 날'을 아직 모르면 사망일로 갈음하되 `base_estimated=True` 표시를
남깁니다.

**⑤ 결과물** — 임박한 순으로 정렬된 `DeadlineItem` 리스트. 예: 사망일 2026-05-03,
오늘 2026-07-17이면:

```python
DeadlineItem(step=StepId.ACCEPT_DECIDE, label="한정승인·상속포기 신고 기한",
             due_date=date(2026, 8, 3), days_left=17,
             base_label="상속개시를 안 날", base_date=date(2026, 5, 3),
             base_estimated=True, law="민법 제1019조 제1항")
DeadlineItem(step=StepId.INHERIT_TAX, label="상속세 신고·납부 기한",
             due_date=date(2026, 11, 30), days_left=136,          # 5/31 + 6개월
             base_label="사망일이 속한 달의 말일", law="상속세 및 증여세법 제67조")
```

**⑥ 행선지** — `ProcedurePlan.deadlines/urgent/overdue`로 분류되어 답변 텍스트,
`data["plan"]`, 그리고 `ics.py`의 캘린더 이벤트가 됩니다.

### `consent.py` — 협의 동의 체크리스트

**① 역할** — "이 결정에는 **누구의** 동의가 필요한가"를 가족관계 그래프에서 계산.
누가 얼마를 가질지는 계산하지 않습니다(경계 2번).

**② 기능** — 가족그래프 해석(`_read_heirs`), 체크리스트 생성(`build_checklist`),
미성년 상속인 + 친권자 공동상속 시 특별대리인 필요 표시.

**③ 트리거** — `planner.build_plan()`이 `build_checklist(family_graph)`로 호출합니다.
받는 것: `AgentInput.family_graph` (프론트/오케스트레이터가 준 dict).

**④ 수행 방식** — `family_graph` 스키마가 아직 확정 전이라 **두 형태를 모두**
받아들입니다: 형태 A(상속인 목록 `heirs: [...]`), 형태 B(현재 `family_graph.engine`이
쓰는 `spouse_alive` + `num_children` 최소형). 모르는 형태면 조용히 `unavailable()`로
비워둡니다 — 스키마 확정 시 `_read_heirs`만 고치면 됩니다.

**⑤ 결과물** — `ConsentChecklist`. 예: `{"spouse_alive": true, "num_children": 2}` →

```python
ConsentChecklist(heir_count=3,
  signers=[Heir(name="배우자", relation="spouse"), Heir(name="자녀 1", ...), Heir(name="자녀 2", ...)],
  notes=["상속재산분할협의서는 상속인 전원의 서명·날인과 인감증명서가 필요합니다.",
         "한 명이라도 빠지면 협의서 전체가 무효가 됩니다."])
```

**⑥ 행선지** — `ProcedurePlan.consent`로 들어가 답변의 "협의에 동의가 필요한 분"
섹션과 `data["plan"]`에 실립니다.

### `prompts.py` — 사실 블록과 서술 (출구)

**① 역할** — 절차 엔진의 계산 결과를 사람이 읽을 답변으로 바꾸는 출구. LLM이 쓰이는
두 지점 중 나머지 하나이며, LLM 없이도 같은 일을 하는 렌더러를 함께 들고 있습니다.

**② 기능** — compose용 시스템 프롬프트(`SYSTEM_COMPOSE`), 사실 블록 직렬화
(`facts_block`), LLM 없는 렌더러(`deterministic_reply`), 슬롯별 되묻기 문구
(`QUESTIONS`), 필수 질문 판정(`blocking_question`).

**③ 트리거** — `graph.py`의 `compose` 노드가 `facts_block`(LLM 경로)과
`deterministic_reply`(폴백)를, `ask` 노드와 `_after_resolve` 분기가
`blocking_question`/`QUESTIONS`를 호출합니다. 받는 것: `ProcedurePlan`과 `HeirState`.

**④ 수행 방식** — `facts_block`은 plan을 `<사실>...</사실>` 텍스트로 직렬화합니다
(이미 지난 기한 → 임박한 기한 → 그 밖의 기한 → 지금 할 일 → 아직 못 하는 일 →
선택지 → 동의 필요자 → 되물을 것 순). `SYSTEM_COMPOSE`는 **이 블록 밖의 날짜·서류·
기관·법조문을 언급하지 못하게** 묶고, 문체 규칙(모바일이므로 짧게, 당장 할 일 하나
먼저, 상투적 위로 금지, 되물음은 한 번에 하나)을 정합니다. `deterministic_reply`는
같은 plan을 마크다운으로 직접 렌더링하는데, 임박하지 않은 기한도 반드시 보여줍니다 —
"아직 멀었다"고 숨기면 사용자가 존재 자체를 모르고 지나갑니다.

**⑤ 결과물** — 문자열. `facts_block` 예시(축약):

```
<사실>
오늘: 2026-07-17
사망일(상속개시일): 2026-05-03
[임박한 기한]
- 한정승인·상속포기 신고 기한: 2026-08-03 (17일 남음) / 근거: 민법 제1019조 제1항
[지금 할 수 있는 일]
- 재산 조회 결과 확인: 기관별로 도착한 조회 결과로...
[안내 문구 — 답변 끝에 반드시 포함]
안내 기준입니다. ...
</사실>
```

**⑥ 행선지** — `facts_block`은 Claude API의 user 메시지로, `deterministic_reply`와
`QUESTIONS`는 그대로 최종 `reply`로 나갑니다.

### `ics.py` — 기한 → 캘린더 파일

**① 역할** — 계산된 기한을 사용자 휴대폰 캘린더에 넣을 수 있는 `.ics` 파일로 변환.
Google Calendar API 대신 `.ics`를 고른 이유: OAuth 동의 흐름이 필요 없고, 아이폰·
안드로이드에서 그냥 열리고, 사망일 같은 민감정보를 외부 서비스로 내보내지 않습니다.

**② 기능** — RFC 5545 형식 생성(`build_calendar`), 이벤트마다 30·7·1일 전 알림
(`VALARM`), 한글이 깨지지 않는 75옥텟 라인 폴딩(`_fold`), 특수문자 이스케이프.

**③ 트리거** — `graph.py`의 `finalize` 노드가 plan에 기한이 있을 때
`build_calendar(plan.deadlines, session_id=..., now=...)`로 호출합니다.

**④ 수행 방식** — 완료되지 않은 기한만 골라 종일 일정(`VEVENT`)으로 만듭니다.
UID를 `단계-세션ID`로 고정해 같은 파일을 다시 받아도 캘린더에 중복 등록되지 않게
하고, 설명에 근거 조문·기산점·디스클레이머를 넣습니다.

**⑤ 결과물** — `.ics` 문자열. 예시(축약):

```
BEGIN:VCALENDAR
X-WR-CALNAME:상속 절차 기한
BEGIN:VEVENT
UID:accept_decide-sess123@heir-navigator
DTSTART;VALUE=DATE:20260803
SUMMARY:[상속] 한정승인·상속포기 신고 기한
BEGIN:VALARM
TRIGGER:-P30D
...
```

**⑥ 행선지** — `data["calendar_ics"]`로 프론트에 갑니다. 프론트가 파일로 내려주면
사용자가 탭 한 번으로 휴대폰 캘린더에 등록합니다.

### `__init__.py` 두 개 — 공개 창구

**① 역할** — 패키지의 공개 인터페이스 선언.
**②–⑥** — `heir_navigator/__init__.py`는 `run`과 `TRIGGER_KEYWORDS`만 재수출해서
오케스트레이터가 내부 구조를 몰라도 되게 하고, `procedure/__init__.py`는 사실 계층의
전 심볼을 한 곳에서 import할 수 있게 모읍니다. 로직 없음.

### (참고) `../../llm/claude.py` — Claude SDK 래퍼 (에이전트 3개 공용)

heir_navigator 소유는 아니지만 이 에이전트의 LLM 호출이 전부 여길 지납니다.
`complete()`(compose용 텍스트 생성)와 `extract()`(`tool_choice` 강제로 구조화 추출,
슬롯용) 두 함수뿐이고, `ANTHROPIC_API_KEY`가 없으면 `LLMUnavailable`을 던져 호출부가
규칙 기반 폴백으로 내려가게 합니다. 모델은 `CLAUDE_MODEL` 환경변수로 교체 가능
(기본 `claude-opus-5`).

---

## 상태 관리 — 멀티턴이 성립하는 방식

서버는 아무것도 기억하지 않습니다. 멀티턴은 세 주체의 협력으로 성립합니다:

```
[턴 N]   agent.py: dump_state → AgentOutput.data["heir_navigator"] ──┐
                                                                     │ 프론트가 보관
[턴 N+1] agent.py: load_state ← AgentInput.context["heir_navigator"] ←┘ 하고 되돌려줌
```

`schemas/agent_io.py`를 건드리지 않으므로 다른 담당자와 충돌하지 않고, 나중에 DB
세션이 생기면 `state.load_state` / `dump_state`만 갈아끼우면 됩니다. **프론트는 이전
턴의 `data`를 그대로 다음 요청의 `context`로 실어 보내야 합니다** — 이걸 빠뜨리면
에이전트는 매 턴 처음 보는 사용자처럼 동작합니다.

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
