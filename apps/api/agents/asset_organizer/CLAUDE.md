# 자산·부채 체크리스트 에이전트 (asset_organizer)

## 역할

예금·주식·펀드·부동산·자동차·퇴직연금(자산)과 부채(대출·카드론·전세자금대출·
임대보증금반환채무를 묶은 "부채" 하나의 카테고리), 보험을 대화형 체크리스트로
모은다. 자산 쪽은 유형별로 개별 카테고리로 하나씩 확인하고, 부채는 여러 유형을
"부채" 카테고리 하나로 묶어서 확인한다 — 두 축의 확인 단위가 원래부터 다르다
(agent.py의 `_ASSET_CATEGORIES`/`_LIABILITY_CATEGORY` 참고, 새 유형을 추가할 때
이 비대칭 구조를 먼저 확인하고 맞출 것).

다 모이면 develop의 공유 계약 `schemas.FinancialProfile`(flat 집계)로 눌러서
`AgentOutput.financial_profile`에 실어 보내고, 동시에 `AgentOutput.handoffs`로
`retirement_planner`에 핸드오프를 건다(체크리스트 끝나면 자연스럽게 은퇴자금
시뮬레이션으로 이어지는 게 원래 의도 — 아래 "빌드 히스토리" 참고).

### 안 하는 일

- **은퇴자금 시뮬레이션은 안 한다.** develop 재작업 이전 세션들은 이 에이전트
  하나가 체크리스트와 시뮬레이션을 다 했지만, 지금은 `agents/retirement_planner/`
  가 전담한다. 계산 로직(engine.py/engine_models.py/adapter.py/format_utils.py)은
  그쪽으로 그대로 옮겨졌다.
- **세법상 금융자산/비금융자산 분류를 추측하지 않는다.** `financial_assets`는
  tax_calculator 담당자가 확정해준 기준(예금·주식·펀드만 금융자산, 부동산은
  `real_estate_value`로 별도, 그 외는 `other_assets`)만 그대로 반영한다. "기타"로
  들어온 항목을 금융자산인지 아닌지 이 에이전트가 대신 판단하지 않는다 —
  tax_calculator가 항목명을 보고 자기 쪽에서 추가로 확인하기로 했다.
- **수익률 기본값을 제시하지 않는다.** `Asset.return_rate`는 사용자가 직접 말한
  값만 담고, 없으면 그대로 None(→ retirement_planner가 0으로 처리)이다. 서비스가
  "연 5% 정도 잡죠" 같은 투자자문성 기본값을 제시하면 안 된다는 경계선.
- **부채 채권자 판정을 하지 않는다.** `financial_debts`(금융기관 채무 여부)는
  채우지 않는다 — `Liability.type`이 자유 문자열이라 자동 판정할 근거가 없고,
  tax_calculator가 채권자 정보로 직접 확인 질문을 넣기로 확정했다.

## 담당 경계

건드리지 않는 파일:
- `orchestrator/` 전체 (router.py, planner.py, registry.py, handoff.py 등)
- `schemas/` 전체 — 새 `AgentName`/`FinancialProfile` 필드가 필요하면 코드로
  먼저 추가하지 말고 팀 논의부터
- 다른 에이전트 디렉토리(`decedent_estate/`, `tax_calculator/`, `heir_navigator/`,
  `heir_share_analyzer/`) — 필요하면 조사만 하고 보고

`agents/retirement_planner/`는 "다른 에이전트"지만 이 프로젝트에서는 예외다 —
아래 "유형 추가 시 주의"에 적은 이유로 asset_organizer 쪽 자산 유형을 넓힐 때마다
같이 손대야 하는 실질적 결합이 있다.

## 지켜온 설계 원칙

1. **조용한 실패 금지.** 파싱/분류에 실패하면 추측해서 채우지 않는다 — 유형은
   알지만 금액이 없으면 그 금액만 콕 집어 되묻고(`extractor.py`), 화이트리스트
   밖 값이 오면 항목을 드롭하지 않고 "기타"로 보존한다(아래 3번). 항목을
   통째로 버리면 실제 자산/부채가 사용자 재무 상태에서 사라져 순자산이
   왜곡된다 — 어느 방향으로 왜곡되든(좋아 보이게든 나빠 보이게든) 안전하지 않다.
2. **틀려도 안전한 방향으로.** `Asset.liquid` 기본값은 부동산·자동차·퇴직연금이
   `False`(비유동)다 — 감가상각·중도인출 불이익 등 이유는 각각 다르지만,
   "실제보다 좋아 보이게" 왜곡되는 쪽보다 "실제보다 나빠 보이게(안전하게)"
   왜곡되는 쪽을 기본값으로 택했다(실제 liquid 판정은 `retirement_planner/
   adapter.py`가 한다 — asset_organizer 자신은 항상 `liquid=None`으로 넘긴다).
   부채 이중 모드도 마찬가지: 정밀 모드로 확정할 근거(월 상환액+종료나이)가
   없으면 단순 모드(총액 한 번 차감)로 남기지, 정밀 모드를 강제로 추론하지
   않는다.
3. **PII 화이트리스트 방어.** 자산/부채/소득 `type`이 LLM 응답에서 화이트리스트
   밖으로 오면(계좌번호·예금주명 등이 섞인 원문일 위험) 원문은 버리고 "기타"로
   대체한다 — 항목 자체(금액)는 보존한다. `_VALID_ASSET_TYPES`는
   `_ASSET_KEYWORDS.keys()`에서, `_VALID_LIABILITY_TYPES`는
   `_LIABILITY_KEYWORDS.keys()`에서 각각 자동 파생되므로 화이트리스트 자체를
   손으로 유지보수할 일은 없다. LLM 시스템 프롬프트의 허용 유형 목록도
   `_build_system_prompt()`/`_build_image_system_prompt()`가 같은 화이트리스트에서
   조립하므로 프롬프트 문구를 손으로 맞출 필요도 없다.
   - 단, 완전 자유텍스트 필드("unclear")는 화이트리스트로 거를 방법이 없다 —
     실제로 실행해서 확인한 결과, `agent._merge_extraction()`이 이 kind를
     의도적으로 건너뛰어 사용자 응답/세션 어디에도 노출되지 않는다(현재는
     안전, 관련 주석이 extractor.py/agent.py 양쪽에 있음). 이 kind를 나중에
     실제로 소비하는 코드를 추가하면 원문을 그대로 노출하지 말 것.
4. **retirement_planner로 정보를 최대한 보존해서 넘긴다.** develop 공유
   `FinancialProfile`은 flat 집계라 유형별 세부(유동성·수익률·부채 정밀/단순
   모드·보험)가 사라진다 — 그래서 `extra["asset_organizer"]`에 itemized 원본을
   그대로 함께 보낸다(`_to_shared_profile()` docstring에 정보 손실 지점을 전부
   정리해뒀다).

## 유형 추가 시 주의 — 실제로 겪은 하드 크래시

새 자산 유형을 추가할 때 아래 화이트리스트/프롬프트는 **자동으로** 따라온다
(코드 수정 불필요):
- `extractor._VALID_ASSET_TYPES` (← `_ASSET_KEYWORDS.keys()`)
- `extractor._VALID_LIABILITY_TYPES` (← `_LIABILITY_KEYWORDS.keys()`, 새 부채
  유형일 때)
- LLM 시스템 프롬프트(`_build_system_prompt()`/`_build_image_system_prompt()`)

하지만 **아래는 손으로 같이 고쳐야 한다** — 안 고치면 새 유형을 가진 사용자가
`retirement_planner`로 넘어가는 순간 `pydantic.ValidationError`로 하드 크래시가
난다(실제로 겪은 이슈):

1. `models.AssetType`(이 폴더) — 새 유형 추가
2. **`agents/retirement_planner/models.py`의 `AssetType`도 별도로 복제 보유하고
   있다** — 여기도 똑같이 추가해야 한다. `retirement_planner/agent.py`의
   `_build_engine_input()`이 `extra["asset_organizer"]["assets"]`의 itemized
   dict를 자기 자신의 `models.Asset(**a)`로 다시 파싱하기 때문에, 이 Literal이
   asset_organizer 쪽과 어긋나면 그 시점에 검증 예외가 난다.
3. 자산이라면 `agents/asset_organizer/agent.py`의 `_ASSET_CATEGORIES`(체크리스트
   개별 카테고리로 확인할지)도 판단해서 추가
4. 기본 유동성을 부동산처럼 비유동으로 두고 싶으면 `retirement_planner/
   adapter.py`의 `_ILLIQUID_BY_DEFAULT_KINDS`와 `_ASSET_TYPE_MAP`도 같이
   (엔진 계산 로직 `engine.py` 자체는 `kind`를 안 보므로 건드릴 필요 없음)
5. 세법상 금융자산으로 볼지는 **tax_calculator 담당자 확정 없이 추측하지 않는다**
   — `agent._FINANCIAL_ASSET_TYPES`에 넣지 말고 기본값(`other_assets`)에 남길 것

부채 유형은 1)~2)에 해당하는 별도 복제가 없다(`Liability.type`이 양쪽 다 자유
문자열) — `_LIABILITY_KEYWORDS`/`_LiabilityLabel`에만 추가하면 된다.

## 미해결 항목

- **`agents/common/` 공유 모듈로 빼야 할 중복**:
  - LLM 파싱 헬퍼 — `extractor.py`가 `decedent_estate/llm_client.py`와 로직이
    거의 같다(코드펜스 제거, JSON 파싱, 환경변수 처리). 지원과 확인 후 통합할 것
    (`extractor.py` 상단 TODO).
  - `AssetType`/`_format_krw`/금액 파싱 정규식 — asset_organizer와
    retirement_planner 사이에 의도적으로 복제해둔 것들(레지스트리 방식에서
    에이전트 패키지는 서로 독립이 원칙이라 cross-agent import를 피하려고
    그랬다)이지만, 위 "유형 추가 시 주의"에서 보듯 실제로는 두 곳이 강하게
    결합돼 있다 — 정말 독립적이어야 하는지, 공유 모듈로 빼는 게 나은지 팀
    논의 필요.
- **이미지 판독 "unclear" 필드의 구조적 위험은 남아 있다** — 지금은 소비하는
  코드가 없어 안전하지만, 화이트리스트로 원천 차단된 게 아니라 "아무도 안
  본다"는 우연에 기대고 있다. 나중에 이 필드를 실제로 쓰게 되면 반드시
  정형화하거나 마스킹할 것.

## 빌드 히스토리 (요약)

- develop의 registry 방식(spec.py 선언 기반)에 맞춰 껍데기를 채움 — 계산
  로직은 옛 세션에서 검증된 것을 그대로 가져왔다(재작업, 재검증 없음).
- 보험 카테고리, 이미지 인식(멀티모달 1회 호출), PII 화이트리스트 보존
  방식(드롭 대신 "기타") 순으로 추가.
- 자동차·퇴직연금(자산)·임대보증금반환채무(부채) 유형 확장, `financial_assets`
  실제 분류(tax_calculator 확정 기준 반영), 퇴직연금 연금형 수령 시 소득
  흐름(`IncomeStream`) 전환(부채 이중 모드와 동일 패턴) 순으로 추가.
- **핸드오프 부재 발견 및 수정**: 체크리스트가 끝나도 `next_action`/`handoffs`가
  전혀 설정되지 않아, 사용자가 "은퇴"/"노후"/"연금" 키워드를 새로 말하지 않는
  한 대화가 asset_organizer에 머물러 있었다(실제 오케스트레이터로 실행해서
  확인). `_finalize()`에서 `retirement_planner`로 핸드오프를 걸도록 수정.
  - 이 조사 중, "퇴직연금"(자산 유형)이라는 문자열 자체가 `retirement_planner`
    의 라우팅 키워드 "연금"의 부분 문자열이라, 체크리스트 도중 사용자가
    "퇴직연금"을 언급하면 `registry.match_keywords()`의 단순 substring
    매칭 때문에 대화가 중간에 retirement_planner로 튕겨나가며 그 턴의
    입력이 통째로 유실되는 것도 함께 발견했다(실측 재현됨).
  - **이 충돌은 이후 팀원이 develop에 직접 커밋(45253e9, PR #45 병합 직후)해서
    고쳤다** — "연금" 키워드를 대체 없이 통째로 제거(`keywords=["은퇴",
    "노후"]`)했고, 커밋 메시지에 "데모 비핵심(서비스는 '상속')"이라는 스코프
    결정도 함께 남겼다. 근본 원인(오케스트레이터의 substring 매칭 방식
    자체)은 여전히 손대지 않은 채로 있다.
  - ⚠️ **이후 팀 계획서 결정으로 retirement_planner가 데모 범위에서 완전히
    제외됐다** — `spec.py`의 `keywords`를 아예 비워서(`[]`) "은퇴"/"노후"
    포함 어떤 문구로도 도달 못 하게 막았다(자세한 내용은
    agents/retirement_planner/CLAUDE.md 참고). `asset_organizer` →
    `retirement_planner` 핸드오프(Fast Path)는 keywords와 무관해서 여전히
    동작한다 — 체크리스트 완료 후 자동 연결은 안 끊겼다.
- **부채 후속질문 게이트가 퇴직연금 후속질문을 가로채던 버그 수정**: 위
  핸드오프 조사 중 발견해뒀던 버그. `_run_turn()`의
  `was_awaiting_liability_followup` 판단이 "이미 답을 받았는지"가 아니라
  `_liabilities_needing_followup(state)`(부채 필드가 여전히 비어 있는지)
  로 매 턴 다시 계산돼서, 부채가 단순 모드로 영구히 비어 있으면(예:
  "몰라요"로 답해 monthly_payment/end_age를 끝내 못 채운 경우) 이 조건이
  그 이후 모든 턴에서 계속 True로 남아 퇴직연금 후속질문의 차례를 영영
  못 오게 만들었다. `pension_followup_resolved`와 대칭으로
  `liability_followup_resolved` 플래그를 추가해, 답을 받은 시점에(설령
  "몰라요"여도) 즉시 종결 처리하도록 고쳤다 — "재질문 금지" 원칙과 반대
  방향 문제였다(답을 받았는데 또 물어보고, 다른 질문 기회를 뺏는 것).
  같은 클래스의 버그(값이 안 채워지면 "대기 중" 판단이 영구히 안 풀리는
  구조)가 다른 다중 턴 흐름(`pending_categories`/`pending_amounts`)에도
  있는지 확인했으나, 그 둘은 매 턴 명시적으로 재계산·초기화되는 구조라
  해당 없음을 확인했다 — 이 버그는 liability/pension 두 후속질문 사이의
  상호작용에 국한됐다.
- **금액 콤마 파싱 버그 수정(P0-3)** — "3,200만원"을 콤마 뒤 "200만원"으로만
  읽어 앞자리가 통째로 사라지던 버그. 원인이 두 군데 겹쳐 있었다: (1)
  `_parse_amount()`가 콤마를 숫자 구분자로 안 걷어내고 있었고, (2) 그보다
  먼저 `_SEGMENT_SPLIT_RE`가 콤마를 세그먼트 구분자로 취급해서 "3,200만원"
  자체가 "3"/"200만원" 두 조각으로 쪼개지고 있었다(1번만 고치면 세그먼트가
  이미 갈라진 뒤라 소용없었다). 둘 다 숫자 사이 콤마는 lookaround로
  걸러내도록 고쳤다. `retirement_planner/agent.py`의 `_parse_amount`
  복제본도 동일하게 고침(코드 주석으로 중복 위치 남겨둠 — `AssetType`
  중복과 같은 문제 클래스, `agents/common/` 공유 모듈 논의 대상에 이미
  있음, 이번엔 급해서 양쪽 다 고치는 것까지만 함).
- **생전/사후 두 축 + 3단계 금액 신뢰도 추가(2026-08-31 팀 계획서 확정 반영)**
  — retirement_planner가 데모에서 빠지면서 asset_organizer가 "상속재산 파악
  전담"이 됐고, 그중 생전(본인 재산 목록화, 기존 기본 동작)뿐 아니라 사후
  (남은 가족이 안심상속 원스톱서비스 등에서 조회한 결과를 해석)까지 이번
  라운드에서 처리 범위에 들어왔다. 세금 계산·배분 판단은 여전히 범위 밖 —
  이번 라운드는 순수하게 목록화 + 신뢰도 표시만.
  - **모드 게이트는 새로 발명하지 않고 `decedent_estate`의 intent 게이트
    (review/prepare, `agents/decedent_estate/agent.py._resolve_intent`)와
    완전히 같은 패턴을 그대로 가져왔다** — `context["mode"]`(flat key, 이번
    턴 명시 답변이 저장된 값보다 우선) → 없으면 조용히 `pre_need`로 기본,
    잘못된 값이면 재확인 질문하고 저장은 안 함. `schemas.AgentInput.axis`
    (오케스트레이터가 "키워드 후보 0개"일 때만 쓰는 라우팅 힌트)와는
    의도적으로 분리 — decedent_estate도 자기 axis와 별개로 intent를 자체
    관리하는 것과 같은 이유.
  - **사후 모드 다기관 조회 해석**: `extractor.extract_disclosures()`를
    새로 추가 — "OO은행은 잔액까지 나왔고 OO증권은 계좌만 확인됐어요"처럼
    한 문장에 여러 기관 결과가 섞여도 기관별 공개 수준(예금·부동산·세금은
    금액까지, 보험은 가입여부만, 투자상품은 잔고 유무만)에 맞춰 유형별
    confirmed/unknown_amount로 나눈다. `extract_from_image()`의 PII 최소화
    원칙(계좌번호·예금주명과 함께 은행/지점명도 결과에서 뺀다)을 그대로
    따라 `DisclosureItem`에는 기관명 필드 자체가 없다 — 구조적으로 못
    담는다. 사후 모드에서도 다기관 패턴이 아니면(`disclosures`가 빈 배열)
    기존 일반 추출 경로로 폴백한다 — 사후 모드가 평범한 자산 언급을 못
    알아듣게 만들면 안 되므로.
  - **3단계 금액 신뢰도**: 기존엔 자산이 "확인됨(금액 있음)"/"미확인
    (아직 언급 안 됨)" 둘뿐이었는데, 중간 단계 `unknown_amount`(존재는
    확인됐지만 금액은 모름 — 사용자가 "몰라요"라고 답했거나 사후 모드에서
    기관이 존재만 확인해준 경우)를 추가했다. 부채/퇴직연금 후속질문의
    "한 번 답하면 다시 안 묻는다" 원칙과 동일하게(오히려 재질문이 더
    무의미한 게 확실한 케이스라 더 강하게) 영구 확정 — 다음 턴에 같은
    항목을 다시 되묻지 않는다.
  - **순자산 계산에서 `unknown_amount` 항목 제외 + 안내**: tax_calculator
    라운드의 "미확인은 0원이 아니다" 원칙과 같은 이유로, 금액 모르는
    항목을 조용히 0으로 합산하면 순자산이 실제보다 적어 보이게 왜곡된다
    (2번 원칙 "틀려도 안전한 방향으로"와 반대). 그렇다고 억지로 추정치를
    넣지도 않는다 — 합계에서 아예 빼고 "N개 항목은 금액이 확인되지 않아
    총액에서 제외됨"이라고 명시해서, 사용자가 총액을 완전한 합으로
    오인하지 않게 한다. `extra["asset_organizer"]`의 itemized 자산에도
    각 항목의 `confidence`를 그대로 실어 보낸다 — tax_calculator 등
    다운스트림이 추가 확인이 필요한 항목을 판단할 수 있도록.
  - `Asset` 모델에 새 필드(`confidence`)를 추가하면서, pydantic v2
    `BaseModel`이 생성자에 넘어온 미지정 필드를 조용히 무시한다는 점을
    직접 확인(`python -c`로 실측)하고 나서 진행했다 — `AssetType` 중복
    때문에 겪었던 하드 크래시(위 "유형 추가 시 주의" 참고)를 다시
    반복하지 않기 위해서였다. 결과적으로 `retirement_planner/models.py`를
    건드리지 않고도 안전했다(itemized 원본은 그쪽에서 `models.Asset(**a)`
    로 재구성하는데, `confidence` 키가 있어도 무시되고 크래시 안 남 —
    단, `retirement_planner` 쪽은 이 필드를 아예 활용하지 않으므로 나중에
    그쪽에서 신뢰도를 실제로 쓰려면 그때 가서 `retirement_planner/
    models.py`의 `Asset`에도 필드를 추가하는 논의가 필요).
