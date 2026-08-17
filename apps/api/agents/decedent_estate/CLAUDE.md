# 유언장 검증 에이전트 (decedent_estate)

## 역할
유언장 텍스트를 받아 민법 §1066 자필증서 형식 요건(자서·연월일·주소·성명·날인)을 점검하고, 판례 기반 카드와 함께 신호등(GREEN/YELLOW/RED) 결과를 반환한다.

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
