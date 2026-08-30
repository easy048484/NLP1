# 은퇴자금 시뮬레이션 에이전트 (retirement_planner)

## 역할

현재 나이·월 생활비만 최소로 확인한 뒤, `asset_organizer`가 남긴
`extra["asset_organizer"]`의 itemized 자산·부채(유동성, 부채 정밀/단순 모드,
연금형 전환 소득)를 그대로 엔진 입력으로 재구성해 85/90/95세 시나리오로
은퇴자금 시뮬레이션을 돌린다. 실질수익률(명목수익률-물가상승률) 하나로 계산하며,
결과는 전부 "오늘 돈 가치" 기준이다.

`asset_organizer`를 거치지 않고 이 에이전트에게 바로 말을 걸면(itemized 데이터가
없으면) develop 공유 `FinancialProfile`의 flat 집계(`real_estate_value`/
`financial_assets`/`other_assets`/`total_debts`)만으로 단순화된 자산·부채를
합성한다 — 부동산은 이때도 기본 비유동으로 처리된다(`_synthesize_assets_from_flat`).

### 안 하는 일

- **자산·부채 체크리스트를 직접 모으지 않는다.** develop 재작업 이전 세션들은
  이 에이전트 하나가 체크리스트와 시뮬레이션을 다 했지만, 지금은
  `agents/asset_organizer/`가 전담한다. 여기서 새로 짠 건 `agent.py`(대화
  흐름)뿐이고, 계산 로직(`engine.py`/`engine_models.py`/`adapter.py`/
  `format_utils.py`)은 옛 세션에서 검증된 걸 그대로 옮겨와 **한 줄도 안
  바꿨다**.
- **수익률 기본값을 제시하지 않는다.** `Asset.return_rate`를 사용자가 직접
  말하지 않으면 0으로 처리한다(`adapter.py`) — "이 정도면 연 5%는 나옵니다"
  같은 투자자문성 기본값을 서비스가 제시하지 않는다는 경계선.
- **퇴직연금을 자동으로 소득 전환하지 않는다.** 연금형으로 받을지/일시금으로
  받을지는 `asset_organizer`가 후속질문으로 확인해서 넘겨준 결과(있으면
  `extra["asset_organizer"]["incomes"]`)를 그대로 받아쓸 뿐, 이 에이전트가
  스스로 "퇴직연금이니 몇 세부터 연금으로 받을 것"이라고 추론하지 않는다.

## 담당 경계

건드리지 않는 파일:
- `orchestrator/` 전체
- `schemas/` 전체
- 다른 에이전트 디렉토리(`decedent_estate/`, `tax_calculator/`, `heir_navigator/`,
  `heir_share_analyzer/`)

`agents/asset_organizer/`는 "다른 에이전트"지만 예외다 — 아래 "유형 추가 시
주의"에 적은 이유로 자산 유형이 늘어날 때마다 실질적으로 같이 손대야 한다.

## 지켜온 설계 원칙

1. **조용한 실패 금지.** 필수 슬롯(현재 나이, 월 생활비)이 없으면 재질문하지,
   임의 기본값을 채우지 않는다. 공유 `financial_profile`에 이미 값이 있으면
   (다른 에이전트/이전 턴이 확인해뒀으면) 재질문하지 않고 그대로 쓴다 — 공유
   프로필을 두는 이유 그 자체.
2. **틀려도 안전한 방향으로.** 부동산·자동차·퇴직연금은 명시적 override가
   없으면 기본 비유동(`liquid=False`) — 잔액 계산(인출 대상)에서 제외해
   "실제보다 좋아 보이는" 쪽으로 왜곡되지 않게 한다. 부채도 정밀 모드로
   확정할 근거(월 상환액+종료나이)가 둘 다 있을 때만 정밀 모드로 계산하고,
   하나라도 없으면 단순 모드(원금 한 번 차감)로 안전하게 처리한다
   (`engine.py`).
3. **수익률 기본값 제시 안 함** (위 "안 하는 일" 참고) — `return_rate` 미입력은
   항상 0.0으로, 절대 임의의 "적정 수익률"을 채우지 않는다.
4. **세법상 금융재산 분류는 이 에이전트 책임이 아니다.** `financial_assets`/
   `other_assets` 분류는 `asset_organizer._to_shared_profile()`이 tax_calculator
   확정 기준으로 이미 끝내둔 값을 그대로 읽기만 한다 — 여기서 재분류하지
   않는다(`_synthesize_assets_from_flat`/`_synthesize_liabilities_from_flat`도
   유형별로 다시 쪼개지 않고 있는 그대로만 합성한다).
5. **이중 계산 금지.** 퇴직연금이 연금형으로 전환돼 `incomes`에 들어가도, 자산
   목록의 퇴직연금 원금은 `liquid=False`라 잔액 계산에 애초에 들어가지 않는다
   — 원금과 소득 흐름이 겹치지 않는다(엔진 레벨 수치 테스트로 확인됨,
   `tests/test_retirement_planner_engine.py`).

## 계약

- `run(payload: AgentInput) -> AgentOutput` 시그니처 변경 금지
- `AgentOutput.financial_profile`은 확정된 슬롯만 채워 돌려준다(모르는 필드는
  None으로 둬서 세션의 기존 값을 덮어쓰지 않게 함, `_own_profile_update()`)
- 엔진 3계층 분리를 유지한다 — 입력 모델이 바뀌어도 `engine.py`/
  `engine_models.py`는 영향받지 않아야 하며, 변환 책임은 전부 `adapter.py`가
  진다(`engine_models.py` 상단 주석 참고)

## 유형 추가 시 주의 — 실제로 겪은 하드 크래시

`asset_organizer`가 새 `Asset.type`/`IncomeStream.type`을 추가하면 여기서도
**반드시** 같이 고쳐야 하는 지점들이 있다 — `agent.py`의 `_build_engine_input()`
이 `extra["asset_organizer"]`의 itemized dict를 **이 폴더 자신의** pydantic
모델(`models.Asset`/`models.Liability`/`models.IncomeStream`)로 다시 파싱하기
때문에, 아래를 안 맞추면 그 즉시 `pydantic.ValidationError`로 하드 크래시가
난다(실제로 겪은 이슈):

1. `models.AssetType`/`models.IncomeType` — asset_organizer 쪽 화이트리스트와
   동일하게 유지(자동 파생 아님, **수동 복제**라 양쪽 다 고쳐야 함)
2. `adapter._ASSET_TYPE_MAP`/`adapter._INCOME_TYPE_MAP` — 엔진 kind로 매핑
   (`engine.py`는 kind를 계산에 안 쓰므로, 세분화된 kind가 필요 없으면 기존
   "other" 계열에 합쳐도 무방 — 다만 나중에 kind별로 분기하고 싶어질 걸 대비해
   구분해두는 편이 안전하다)
3. 기본 비유동으로 두고 싶은 자산이면 `adapter._ILLIQUID_BY_DEFAULT_KINDS`에도
   추가
4. 새 kind 값 자체는 `engine_models.EngineAssetKind`/`EngineIncomeKind`
   Literal에도 추가해야 pydantic이 통과시킨다

## 미해결 항목

- **`agents/common/` 공유 모듈로 빼야 할 중복** — `AssetType`/`IncomeType`이
  asset_organizer와 이 폴더 양쪽에 수동으로 복제돼 있다(cross-agent import를
  피하려는 의도적 설계였으나, 위 "유형 추가 시 주의"에서 보듯 실질적으로는
  강하게 결합돼 있다). `_format_krw`/`_parse_amount`류 헬퍍 함수도 마찬가지로
  복제돼 있다(`agent.py` 상단 주석에 명시). 공유 모듈로 뺄지, 지금처럼 복제를
  유지하되 회귀 테스트(`test_local_format_krw_matches_retirement_planner_copy`
  같은)로 갈라짐만 막을지 팀 논의 필요.
- **퇴직연금 여러 건 동시 확인의 단순화** — `asset_organizer`가 퇴직연금
  수령 방식을 물을 때 부채 정밀 모드와 동일한 "여러 건이면 첫 번째만" 단순화가
  있다. 이 에이전트 입장에서는 `extra["asset_organizer"]["incomes"]`에 들어온
  것만 그대로 반영하므로 영향은 없지만, 두 번째 이후 퇴직연금 건은 소득 전환
  기회 자체가 없다는 점은 알아둘 것.
- ⚠️ **asset_organizer 쪽 상호작용 버그로 incomes가 비어 있을 수 있다(미수정)**
  — 같은 대화에 단순 모드 부채(필드가 끝내 안 채워진 경우)와 퇴직연금이
  함께 있으면, 부채 후속질문 게이트가 매 턴 다시 발동해 퇴직연금 후속질문
  답변을 가로채는 상호작용 버그가 실측으로 발견됐다(`agents/asset_organizer/
  CLAUDE.md` 미해결 항목 참고). 이 에이전트 입장에서 증상은 "분명 연금형으로
  답했다는데 `extra["asset_organizer"]["incomes"]`가 비어 있음"으로 나타난다
  — `_build_engine_input()` 자체의 버그가 아니라 상류(asset_organizer) 문제.

## 빌드 히스토리 (요약)

- develop의 registry 방식에 맞춰 껍데기를 채움 — 계산 로직(engine.py 등)은
  옛 세션에서 검증된 것을 그대로 가져왔다(한 줄도 안 바꿈).
- `asset_organizer`가 자산 유형을 자동차·퇴직연금으로 넓히면서 `models.py`/
  `adapter.py`/`engine_models.py`도 함께 확장(위 "유형 추가 시 주의" 참고,
  실제로 크래시를 겪고 나서 정리된 절차).
- 퇴직연금 연금형 수령 확인 시 `IncomeStream`을 만들어 시뮬레이션에 반영하는
  기능 추가 — 부채 이중 모드와 완전히 같은 패턴(한 번만 후속질문, 강제 재질문
  없음)을 재사용했다. `engine.py`는 kind를 안 보므로 무변경.
- **실제 대화 흐름 연결을 오케스트레이터로 실행해서 검증** — 단위 테스트로
  `extra["asset_organizer"]` 파싱이 맞는 것과, 실제 대화가 asset_organizer
  체크리스트 완료 후 여기까지 자동으로 이어지는 것은 별개였다. asset_organizer
  가 핸드오프 신호를 안 보내던 시절에는, 사용자가 "은퇴"/"노후"/"연금" 키워드를
  새로 말하지 않는 한 이 에이전트가 아예 실행되지 않았다 — asset_organizer
  쪽에 핸드오프를 추가해 수정(자세한 내용은 asset_organizer/CLAUDE.md의
  빌드 히스토리 참고).
- **라우팅 키워드 "연금" 제거(임시 방어)** — 위 핸드오프 조사 중 발견된
  "퇴직연금"/"연금으로 받을게요" 등과의 substring 충돌 때문에, `spec.py`의
  키워드를 단독 "연금" → "연금 계산"/"예상 연금"으로 좁혔다. **근본 원인은
  오케스트레이터 `registry.match_keywords()`의 substring 매칭 방식 자체이고,
  이건 팀 논의 대상이라 손대지 않았다** — 이번엔 "연금"이 일으키는 이 특정
  충돌만 우리 담당 에이전트의 키워드 조정으로 임시 방어한 것이다. 완전한
  해결책이 아니라서, `spec.py`의 example_utterances에 남아 있는 "연금으로
  생활비가 충당되나요?"는 이제 단독 키워드로는 안 걸린다(실제 라우팅
  테스트로 확인됨, `tests/test_retirement_planner_keyword_collision.py`) —
  "은퇴"/"노후"로 커버되지 않는 순수 "연금" 질의 표현이 새로 생기면 이
  트레이드오프가 또 드러날 수 있다.
