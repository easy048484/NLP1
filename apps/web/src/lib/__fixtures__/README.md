# `/chat` 계약 fixture

프론트 파서(`lib/api.ts` `normalizeChatResponse`)가 **실제 백엔드 응답**에서
안 깨지는지 지키는 안전판. 시나리오별로 요청/응답 한 쌍을 파일로 박아둔다.

```
__fixtures__/
  requests/   <name>.json  — 백엔드에 보낼 AgentInput (지금 커밋돼 있음)
  responses/  <name>.json  — 그 요청에 대한 실제 응답 (백엔드 띄울 수 있는 사람이 채움)
```

`contract.test.ts` 가 `requests/` 를 순회하며 대응하는 `responses/` 파일이
있으면 `normalizeChatResponse` 에 통과시켜 검증하고, 없으면 그 시나리오를
**자동 skip** 한다. 그래서 응답을 아직 안 캡처해도 CI 는 초록이다.

## 응답 캡처 방법

1. 백엔드 실행 (`apps/api`)
   ```bash
   # LLM 켜고 (실제 합성 답변·verification 을 보려면 필요)
   ANTHROPIC_API_KEY=sk-... uvicorn main:app --port 8000
   # 또는 키 없이 — 봉투 모양(agents/path/verification/data 네임스페이스)은 동일,
   # reply 만 concat 폴백이 된다. 계약 테스트 목적이면 이걸로도 충분.
   ```
2. 캡처 (레포 루트에서)
   ```bash
   cd apps/web/src/lib/__fixtures__
   for s in standard full_pipeline verification_fail followup; do
     curl -s http://localhost:8000/chat \
       -X POST -H 'content-type: application/json' \
       -d @requests/$s.json | python3 -m json.tool > responses/$s.json
   done
   ```
3. `npm test` — skip 이던 시나리오가 켜진다.

## 시나리오 의도

| name | 노리는 것 |
|---|---|
| `standard` | 단일 에이전트 (`path: "standard"`, contribution 1개) |
| `full_pipeline` | 멀티 에이전트 (`path: "full"`, contribution 2개 이상 — 멀티 카드가 실제로 뜨는지) |
| `verification_fail` | `verification.ok === false` — "숫자 확인 필요" 배지. LLM 켠 상태로 숫자 많은 질문을 몇 번 돌리다 걸린 턴을 저장. 안 걸리면 `orchestrator/compose.py` 의 `llm_synthesize` 를 잠깐 목킹해 강제 |
| `followup` | 에이전트가 `pending_questions` 를 되묻는 응답 (후속질문 블록) |

## 주의

- **더미 데이터만.** 실명·주민번호·실제 금액 넣지 말 것 — fixture 는 레포에 커밋된다.
- 응답을 다시 캡처했는데 `contract.test.ts` 가 빨개지면 = 백엔드가 계약을
  바꿨다는 신호. 파서(`api.ts`)를 새 모양에 맞추고 같은 커밋에 넣는다.
