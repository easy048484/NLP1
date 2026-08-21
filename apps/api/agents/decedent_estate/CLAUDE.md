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
6. 이 에이전트는 유언장 본문·추출값을 자체적으로 저장하지 않는다.
   요청 처리 중 메모리에서만 다루고 응답 반환 후 폐기한다.
   로깅 시에도 유언장 본문을 남기지 않는다.
   (세션 연속성은 오케스트레이터 계층의 책임 — docs/privacy_notes.md 참조)

## 계약
- 입출력: apps/api/schemas/agent_io.py 의 AgentInput/AgentOutput 준수
- run(payload: AgentInput) -> AgentOutput 시그니처 변경 금지
- orchestrator/router.py 는 절대 수정하지 않음

## 빌드 순서
1) rules/requirements.json → 2) 연월일 파서+요건 판정기+테스트 → 3) 마스킹 → 4) LLM 추출 연결
- 3), 4)는 **성명(name) 요건에 한해** 완료됨: masking.py(민감정보 제거) →
  llm_client.py(정규식이 못 찾은 경우에만 호출, 유언자 본인 성명만 추출) →
  requirement_checker.extract_name_with_fallback() 로 연결.
- 날짜/주소는 여전히 정규식 전용이며, LLM 폴백이 없다 (docs/known_limitations.md
  의 항목들이 아직 해당 요건에 남아 있음).
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
  - **none("유언장이 없거나 찾지 못했습니다")** → 요건 판정 대상 자체가 없으므로
    intent 게이트보다 먼저 갈라내 `_run_no_will_pipeline()` 로 보낸다. unknown과
    마찬가지로 민법 5방식이 아닌 UI sentinel이라 will_types 배열이 아니라
    rules/will_types.json 의 `no_will` 키에 문구를 둔다.
    - **범위를 의도적으로 좁혔다**: 유언장 탐색 안내(어디에 뒀는지 찾는 법)는
      하지 않는다. 유일한 예외가 공정증서 고지인데, 이것도 "뒤져보라"는 탐색
      조언이 아니라 "원본이 공증사무소에 보관되어 아직 확인되지 않은 경로가
      하나 있다"는 사실 고지다.
    - **상속인 범위·지분·유류분은 답하지 않는다** — heir_navigator 영역이라
      침범하면 두 에이전트가 서로 다른 답을 할 위험이 있다. "확인된 유언장이
      없는 경우 일반적으로 법정상속 절차를 따릅니다"까지만 말하고 넘긴다
      (절대 원칙 2 무단정 유지 — "유언장이 없으니 법정상속입니다" 금지).
    - ⚠️ **공정증서 고지 문구는 검증된 사실까지만 적었다.** 원본이 공증사무소에
      보관된다는 점은 법제처 '찾기쉬운 생활법령정보'로 확인했으나, 유언 존재
      여부를 조회하는 통합 검색 제도(기관명·절차)는 확인하지 못해 기관명·URL을
      특정하지 않고 "공증사무소를 통해 확인" 수준으로 낮췄다. 확인 없이 기관명을
      채워 넣지 말 것 — 회귀 테스트(`test_decedent_no_will.py`)가 막고 있다.
    - ⚠️ heir_navigator 핸드오프는 **스텁**이다. next_action 포맷은 handoff.py
      규약 2번으로 확립돼 있어 notarial과 같은 상수를 재사용하지만, 넘겨받은
      heir_navigator 가 "유언장 없음"을 어떻게 초기 상태로 반영할지는 팀 협의
      대기 중이다(정민님 담당).
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
