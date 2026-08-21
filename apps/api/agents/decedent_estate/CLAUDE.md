# 유언장 검증 에이전트 (decedent_estate)

## 역할
유언 방식(민법 5방식, rules/will_types.json)을 먼저 확인해 분기한다. 방식이
자필증서(§1066, handwritten) 또는 녹음(§1067, recording)이면 각각의 형식 요건을
점검해 판례·조문 기반 카드와 함께 신호등(GREEN/YELLOW/RED) 결과를 반환한다.
공정증서(§1068)는 검증·검인 모두 불요 안내만, 비밀증서(§1069)·구수증서(§1070)는
요건 요약 + 자동 점검 미지원 안내만 한다. handwritten/recording(및 unknown)은
방식 확인 다음으로 intent(이용 목적: review=점검 | prepare=생전 준비 가이드)도
확인해 분기한다 — 자세한 내용은 아래 빌드 순서 5)를 참고.

## 절대 원칙
1. 판정은 룰 엔진이 한다. LLM은 텍스트에서 값 추출(날짜 문자열, 주소·성명 유무)만 한다.
2. "무효입니다/유효합니다" 단정 표현 금지. "무효로 판단한 판례가 있습니다" 패턴만 사용.
3. 판례 카드는 rules/precedents.json에 있는 것만 표시. LLM이 판례를 생성·인용하는 것 금지.
4. 마스킹(주민번호·계좌·전화 치환) 이전의 원본 텍스트를 LLM API에 보내지 않는다.
   성명·주소·날짜는 요건 판정에 실제로 필요한 값이라 마스킹 대상에서 제외한다
   (masking.py 참조 — 판정에 불필요한 정보만 최소한으로 제거).
5. 상세 판정 정책과 화면 문구는 docs/요건판정_문구_스펙_v1.md 를 따른다.
6. 이 에이전트는 자체적으로 저장하지 않으며, 오케스트레이터 세션에는
   판정 결과와 확인 답변만 전달한다. 유언장 원문은 전달하지 않는다.
   요청 처리 중 메모리에서만 다루고 응답 반환 후 폐기하며, 로깅 시에도
   유언장 본문을 남기지 않는다.
   (C안 확정 — docs/privacy_notes.md, 구현은 state.py)

## 계약
- 입출력: apps/api/schemas/agent_io.py 의 AgentInput/AgentOutput 준수
- run(payload: AgentInput) -> AgentOutput 시그니처 변경 금지
- orchestrator/router.py 는 절대 수정하지 않음

## 빌드 순서
1) rules/requirements.json → 2) 연월일 파서+요건 판정기+테스트 → 3) 마스킹 → 4) LLM 추출 연결
- 3), 4)는 **성명·연월일·주소 세 요건 모두** 완료됨: masking.py(민감정보 제거) →
  llm_client.py(정규식이 못 찾은 경우에만 호출) → requirement_checker.py 의
  extract_*_with_fallback() 세 함수로 연결.
  - **성명**: extract_name_with_fallback() → llm_client.extract_testator_name().
    LLM이 이름을 찾으면 곧바로 "present"로 확정한다(성명은 찾음/못찾음만 있고
    등급이 갈리지 않음).
  - **연월일**: extract_date_with_fallback() → llm_client.extract_will_date().
    성명과 달리 LLM이 등급(day_missing/verbal_specified 등)을 직접 정하지
    않는다 — 원문 그대로의 날짜 "문자열"만 반환하고, 그 문자열을
    date_parser.parse_dates()에 다시 통과시켜 규칙 엔진이 등급을 매긴다.
    **여러 날짜가 섞인 경우(multiple_dates_mixed)는 폴백 대상이 아니다** —
    작성일 "선별"은 절 추출이 아니라 사실 판단에 가까워 신뢰 모델이 다르고,
    잘못 선별해도 형식상 결과가 나와 실패가 조용히 묻힐 위험이 있다(팀 결정
    2026-08-21, docs/known_limitations.md 3-4 — 별도 이슈로 사용자 확인
    질문 방식을 검토 중).
  - **주소**: extract_address_with_fallback() → llm_client.extract_will_address().
    연월일과 동일한 원칙 — LLM은 주소 문자열만 찾고, 그 문자열을
    _ADDRESS_UNIT_RE/_ADDRESS_DISTRICT_RE에 다시 통과시켜 full_address/
    city_district_only를 가른다. 이미 등급이 매겨진 결과(예: city_district_only,
    2012다71688 "동만 기재 무효" 판정)는 LLM이 절대 덮어쓰지 않는다 — 정규식이
    `absent`를 반환했을 때만 호출된다.
  - 셋 다 `extracted["extraction_method"]`(`"regex"|"llm"|"none"`)로 어느
    경로에서 값이 왔는지 노출한다.
  - **날짜의 실제 개선 폭은 주소보다 좁다** — 주소는 재산 문맥 줄 제외
    규칙(known_limitations.md 2-1) 때문에 "존재하는데 통째로 가려지는"
    구조적 버그가 있어 LLM 폴백이 실질적으로 해결하지만, date_parser 는 그런
    줄 단위 배제 로직이 없다. 또한 LLM이 날짜를 "원문 그대로"만 반환하고
    재구성하지 않기 때문에(팀 결정), 정규식이 아예 인식 못 하는 새 키워드
    (예: "생신")는 LLM 폴백을 거쳐도 여전히 absent로 남는다 — 자세한 내용은
    docs/known_limitations.md 3-1 참고.
- **유언 방식 분기**(rules/will_types.json, will_types.py)가 agent.run() 맨 앞단에
  추가됨: context.will_type 이 없으면 방식을 먼저 묻는다.
  - handwritten/unknown(기본값 자필증서 적용) → requirement_checker.py 파이프라인
  - **recording(§1067)** → recording_checker.py 파이프라인 (will_types.json 의
    support: "full"). 대본(전사) 텍스트 기준으로 5개 요건(유언 취지/유언자 성명/
    연월일/증인의 정확함 확인/증인 성명) 전부 "정규식 우선 → 5개 중 하나라도
    못 찾으면 llm_client.extract_recording_fields() 를 한 번만 호출해 나머지를
    함께 보완"하는 구조다 (항목별로 따로 호출하지 않음 — 구어체 대본은 정규식만으로
    잡기 어렵다는 게 구조적 한계라 LLM을 주 폴백 경로로 삼음). 나머지 2개
    (증인 실제 참여 여부/증인 결격 여부)는 사용자 확인으로 판정한다.
    requirement_checker._build_result/_load_rules/extract_name 과
    date_parser.parse_dates 를 그대로 재사용해 등급표 중복을 만들지 않는다.
  - notarial/secret/oral → 요건 판정을 아예 돌지 않고 안내만 한다.
  - result_formatter.py 는 summarize()/pending_questions()/format_result() 가
    formal_ids·messages(SummaryMessages)를 파라미터로 받도록 일반화되어
    handwritten·recording 두 요건 집합을 하나의 §3 렌더링 로직으로 처리한다
    (§3-1 A/B/C 문구만 will_type별로 다르고, 나머지는 공통).
5) **피상속인(생전 준비) 모드 — intent 게이트**가 will_type 게이트 다음 단계로
   agent.run() 에 추가됨: context.intent 가 "review"(기본, 이미 있는 유언장/대본
   점검)인지 "prepare"(아직 작성 전, 요건별 작성 가이드)인지 확인한다.
  - intent 미지정(context에 키 자체가 없거나 None)이면 조용히 review로 기본
    동작한다(하위 호환 — intent를 모르는 기존 호출부도 그대로 review 파이프라인).
    값이 있는데 화이트리스트("review"/"prepare") 밖이면 will_type 게이트와 같은
    패턴으로 재질문한다(rules/will_types.json 의 intent_question,
    will_types.intent_question()). 이 게이트는 full 지원 방식
    (handwritten/unknown/recording)에서만 의미가 있다 — notarial/secret/oral은
    intent 값과 무관하게 기존 안내 전용 분기를 그대로 탄다.
  - intent == "prepare"이면 요건 판정을 돌리지 않고, rules/requirements.json 의
    각 요건에 새로 추가된 guide 필드(instruction/mistake_sentence/
    mistake_precedent_id/extra_note)를 result_formatter.format_guide()로
    렌더링해 "✅/❌" 대신 "📝 {요건}: {가이드 문구}" 형태로 안내한다. 판례 인용은
    review 모드와 동일하게 precedents.json 을 거쳐 만든다(판례 재생성 금지
    원칙은 가이드 모드에도 그대로 적용). handwritten 5요건·recording 7요건
    전부 guide를 갖고, interseal(법정 요건 아님)은 guide 대상이 아니다.
  - 사용자가 이미 초안(대본) 텍스트를 갖고 있으면(has_draft_text — context.
    has_draft 명시 우선, 없으면 user_message 비어있지 않음으로 유추) prepare
    모드에서도 가이드 문구 뒤에 기존 review 파이프라인
    (_run_handwritten_pipeline/_run_recording_pipeline) 결과를 그대로 이어
    붙인다 — 판정 로직 자체는 절대 중복 구현하지 않고 재사용만 한다. 응답
    data에는 "guide"(요건별 가이드 payload)와, 초안이 있을 때만 "review"
    (기존 review 파이프라인의 data 그대로) 두 키가 함께 담긴다.
6) **네임스페이스 규약 전환**(orchestrator/handoff.py 규약 1번)이 완료됨:
   상태를 `context["decedent_estate"]` 에서 읽고 `data["decedent_estate"]` 에
   써서 돌려준다 (state.py 의 `DecedentState`/`load_state`/`dump_state` —
   heir_navigator/state.py 의 STATE_KEY 패턴을 그대로 따랐다).
  - 이 전환으로 `handoff.LEGACY_FLAT_CONTEXT_AGENTS` 에서 빠졌고, 이제
    오케스트레이터가 세션에 상태를 저장·복원해준다(TTL 2시간). 그전에는
    저장이 아예 없어서 매 턴 프론트가 전체 context를 재전송해야 했다.
  - **저장 정책은 C안**(docs/privacy_notes.md): will_type·intent·확인 답변·
    요건별 판정 결과·pending_questions 만 담고 **유언장 원문은 담지 않는다.**
    `DecedentState` 에 원문 필드 자체를 두지 않아 구조적으로 막았다.
  - 전환기 안전망으로 평면 키(context 최상위의 will_type 등)도 계속 읽는다.
    우선순위는 **평면 키(이번 턴 입력) > 네임스페이스(지난 턴 상태)** 다 —
    사용자가 답을 바꿔 다시 보냈을 때 지난 턴 값이 이기면 안 되기 때문
    (handoff.build_agent_context 의 "이번 턴에 명시적으로 답한 값이 우선"과
    동일한 원칙). 응답 data 에도 기존 평면 키를 당분간 함께 내보낸다.
  - ⚠️ 아직 안 한 것: 원문 없이 **저장된 판정 결과에 새 확인 답변만 병합하는
    경로**는 미구현이다. 지금은 매 턴 원문이 다시 오는 것을 전제로 평면 폴백이
    받쳐주고 있다. 프론트가 원문 재전송을 멈추면 이 경로가 필요해진다.
