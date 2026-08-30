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
  - ⚠️ **다만 이 해결 방식은 완전하지 않다(실측 확인)** — "연금"을 대체 없이
    빼서 "연금 계산해줘"/"제 예상 연금이 얼마나 될까요" 같은 순수 연금
    질의도 이제 키워드 후보 0개가 되어 default_agent(heir_navigator)로
    새버린다(`tests/test_retirement_planner_keyword_collision.py`의
    `test_pure_pension_query_now_falls_through_to_default_agent` 참고). "데모
    비핵심" 스코프 결정상 당장은 허용된 트레이드오프로 보이지만, 재논의
    여지가 있다.
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
