# 로컬 프론트 확인 방법

프론트 수정 후 눈으로 확인하는 두 가지 방법.

> 방법 B(fixture 목)는 `src/lib/__fixtures__/responses/*.json` 캡처 파일이 필요하다.
> 아직 레포에 없으면 팀에서 캡처본을 받아 그 경로에 두거나 방법 A를 쓴다.

---

## 방법 A — API 연결 (권장)

Docker·DB 없이도 된다. 루트 `.env`에 `ANTHROPIC_API_KEY`가 있으면 LLM까지 실제로 돈다.
`DATABASE_URL`을 비우면 세션은 인메모리(새로고침하면 초기화)로 동작한다.

```bash
# 터미널 1 — API (apps/api)
cd apps/api
DATABASE_URL= APP_ENV=local PURGE_INTERVAL_SECONDS=0 \
  .venv/bin/uvicorn main:app --reload --port 8000

# 터미널 2 — 프론트 (apps/web). 반드시 5173 포트 (API CORS_ORIGINS 기본값)
cd apps/web
npm run dev
```

→ http://localhost:5173 접속. `apps/web`의 dev 서버는 기본으로 `http://localhost:8000`
을 API로 본다(`vite.config.ts` / 루트 `.env`의 `VITE_API_BASE_URL`).

세션·가족관계까지 DB에 저장하며 보고 싶으면 `DATABASE_URL=` 을 빼고(=루트 .env 값 사용)
로컬 Postgres를 먼저 띄운다:

```bash
docker compose -f infra/docker-compose.yml up db     # Postgres만
cd apps/api && .venv/bin/alembic upgrade head          # 최초 1회
```

또는 전체 스택 한 번에: `docker compose -f infra/docker-compose.yml up`

---

## 방법 B — 백엔드 없이 fixture (빠른 레이아웃 확인)

캡처된 응답(`src/lib/__fixtures__/responses/*.json`)을 목 서버가 그대로 돌려준다.

```bash
cd apps/web
node _mock/server.mjs                                  # 터미널 1 (:8787)
VITE_API_BASE_URL=http://localhost:8787 npm run dev    # 터미널 2
```

→ http://localhost:5173/chat 입력창에 `fixture:<이름>`:

- `fixture:demo-final/T4` — 재산·부채 정리 카드 + 금액 입력 카드
- `fixture:demo-final/T3` — 재산·부채 정리 (수집 중)

axis가 필요하면 온보딩을 거치거나 DevTools 콘솔에서
`sessionStorage['eznext.consult_axis']='pre_need'` 후 새로고침.

---

## 스크린샷 자동화 (Playwright)

`apps/web`에서 실행. `npx playwright install chromium` 최초 1회 필요.

```bash
node _mock/drive.mjs <태그>       # 방법 B: light/dark × 4뷰포트 × 4케이스
node _mock/real.mjs               # 방법 A: 실제 대화 4턴 → 카드 스샷 (인자로 BASE URL)
node _mock/one.mjs                # 방법 B: 빠른 2컷
node _mock/verify.mjs             # 방법 B: 가족 인테이크 + 금액 카드 light/dark
```

출력은 `_mock/_shots/`(gitignore). 다른 경로에 저장하려면 `SHOT_DIR=... node _mock/drive.mjs`.
