# 라우팅 채점 (routing eval)

사용자 발화마다 **정답 에이전트**를 붙여 두고, 실제 파이프라인이 **어느 에이전트로 보냈는지**
비교해 점수를 낸다. `spec.py`/프롬프트를 고치기 전후로 같은 골든셋을 돌려 숫자로 회귀를 잡는
용도다 (`docs/라우팅방식변경.md` "다음 단계 — 골든셋").

결과 파일에는 **답변 본문까지** 들어 있어서, 답변 품질 채점(코드 규칙 검사 + AI 심사, 담당: 지원)이
같은 파일을 입력으로 쓴다.

## 실행

```bash
cd apps/api
python -m evals.routing.run --label baseline        # LLM 라우팅 (루트 .env 의 ANTHROPIC_API_KEY 사용)
python -m evals.routing.run --llm off --label rules # 키워드 규칙 라우팅만 (LLM 없을 때의 폴백 경로)
python -m evals.routing.run --only flow-demo-A      # 시나리오 골라서
python -m evals.routing.run --tag hijack:asset      # 특정 태그 턴만 채점 (앞 턴은 이력용으로 실행)
python -m evals.routing.run --list                  # 시나리오 목록
```

- DB 는 쓰지 않는다. 세션은 인메모리, `DATABASE_URL` 은 무시한다.
- 시나리오 하나 = 세션 하나. 안의 턴들은 같은 `session_id` 로 순서대로 보낸다(이어가기/전환 판단에
  실제 대화 이력이 들어가야 하므로).
- 매 턴 실제 에이전트가 끝까지 돌기 때문에(답변 본문을 남기려고) 58턴 전체는 5~10분, API 비용이 든다.
  라우팅만 빨리 보고 싶으면 `--only`/`--tag` 로 줄인다.
- 결과: `results/<날짜-시각>_<커밋>_<라벨>_llm-<모드>.{json,md}`.

## 골든셋 (`golden.json`)

```jsonc
{
  "id": "flow-demo-A",           // 시나리오 id (파일명·필터에 씀)
  "title": "...",
  "axis": "post_death",          // 온보딩 상담 구분. pre_need | post_death | null
  "turns": [
    {
      "message": "상속세는 얼마나 나와요?",
      "expected": ["tax_calculator"],                 // 이 턴에 실행돼야 하는 에이전트 집합 (순서 무관)
      "also_ok": [["asset_organizer", "tax_calculator"]], // 정답으로 인정할 다른 집합 (선택)
      "forbid": ["asset_organizer"],                  // 실행되면 무조건 실패 (선택)
      "tags": ["switch", "hijack:asset"]              // 분석용 라벨 (선택)
    }
  ]
}
```

정답 근거는 각 에이전트의 `spec.py`(description/example_utterances), `docs/데모_시나리오_0830.md`,
`docs/heir_navigator_실험_시나리오_0906.md` 다. 정답이 애매한 턴은 `also_ok` 로 여러 집합을 허용하고
`ambiguous` 태그를 붙였다 — 팀에서 정답을 확정하면 `also_ok` 를 지우면 된다.

자주 쓰는 태그: `fresh`(새 세션 첫 턴) · `continue`(직전 에이전트 이어가기) · `switch`(주제 전환) ·
`multi`(복수 에이전트) · `hijack:<agent>`(다른 에이전트 키워드가 섞인 답변 — 가로채면 안 됨) ·
`inertia`(직전 에이전트에 붙잡히면 안 됨) · `boundary:<agent>`(인접 에이전트와의 경계) ·
`no_keyword`(키워드 0개 — LLM 이 뜻으로 골라야 함) · `pending_reply`(답변 대기 상태에서의 턴).

## 채점 규칙 (턴 단위)

| 지표 | 뜻 |
|---|---|
| **pass** | `actual == expected`(또는 `also_ok` 중 하나) **이고** `forbid` 에이전트가 없음. **기준 점수 = pass 턴 / 전체 턴** |
| exact | 집합이 정확히 일치 (forbid 는 안 봄) |
| covered | expected 가 전부 실행됨 — 덤이 붙어도 인정하는 느슨한 지표. "정답이 빠짐"과 "덤이 붙음"을 구분하려고 둠 |
| per_agent precision/recall | 턴마다 expected 집합 vs actual 집합으로 TP/FP/FN 을 센다 |
| confusion | 오답 턴의 expected → actual 분포 |

턴 기록에는 이것도 남는다: `keyword_hits`(규칙 경로 힌트), `llm_route`(라우팅 LLM 이 고른 이름과
한 문장 근거 — `llm.claude.extract` 를 감싸서 잡음, planner 는 안 건드림), `path`, `next_action`,
`reply`, `contributions`(에이전트별 원문), `financial_profile`, `will_status`, `data`, `elapsed_sec`.

## 결과 파일 읽는 법 (답변 채점용)

- `*.md` — 요약표 → 턴별 표(판정·expected·actual·LLM 근거) → **답변 본문**(시나리오/턴 순서대로,
  ` ```text ` 블록). 사람이 읽는 용도.
- `*.json` — 같은 내용의 구조화 버전. `scenarios[].turns[]` 를 돌면서 `message` / `reply` /
  `contributions` / `data` 를 꺼내면 된다. 코드 규칙 검사(필수·금지 문구, 기한 날짜)는 이쪽을 읽는다.

## 기준선 (2026-09-24, 커밋 c5eb017, 코드 수정 전)

| 라우팅 모드 | 정확도 (pass / 58턴) | covered | 결과 파일 |
|---|---|---|---|
| LLM 라우팅 (`--llm auto`, claude-opus-5) | **58 / 58 = 100.0%** | 100.0% | `results/20260924-1111_c5eb017_baseline_llm-auto.*` |
| 키워드 규칙만 (`--llm off`, LLM 불가 시 폴백 경로) | 44 / 58 = 75.9% | 79.3% | `results/20260924-1118_c5eb017_baseline_llm-off.*` |

LLM 라우팅은 also_ok(느슨한 정답) 없이 전부 1순위 정답과 정확히 일치했다. 규칙 경로의 오답 14건은
문서(`docs/라우팅방식변경.md`)가 LLM-first 로 바꾼 이유 그대로다 — 키워드 없는 발화의 관성
(`큰애한테 다 주고 싶은데` → asset_organizer), 답변 안 자산 단어에 의한 하이재킹
(`빚이 재산보다 많으면` / `재산은 아파트 5억이랑…` → asset_organizer), 답변 대기 중 새 주제 고착
(`유언 얘기는 알겠고 이제 상속 신고는` → decedent_estate), 키워드 복수 매칭으로 인한 덤 실행.

이후 `spec.py`/프롬프트를 바꾸면 같은 명령으로 다시 돌려 `summary.accuracy` 와 `confusion` 을 위 표와
비교한다. `tests/test_routing_golden_live.py` 는 `pytest --live` 로 같은 골든셋을 돌려 정확도가
85% 아래로 내려가면 실패한다.
