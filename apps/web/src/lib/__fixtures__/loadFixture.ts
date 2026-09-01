/**
 * 실제 백엔드 `/chat` 요청·응답을 캡처한 fixture 로더.
 *
 * 왜: 프론트 파서가 깨지는 건 늘 "백엔드가 응답 모양을 바꿨는데 조용히
 * undefined" 였다. 시나리오별 실제 응답을 파일로 박아두고 `normalizeChatResponse`
 * 에 통과시키면, 백엔드가 계약을 바꾼 순간(= 누군가 fixture 를 다시 캡처하는
 * 순간) 테스트가 빨개진다.
 *
 * 캡처 방법은 같은 폴더 README.md 참고. `requests/<name>.json` 은 지금 커밋돼
 * 있고, `responses/<name>.json` 은 백엔드를 띄울 수 있는 사람이 채운다.
 * 응답 파일이 아직 없는 시나리오는 contract.test.ts 가 자동으로 skip 한다.
 *
 * Vite 의 `import.meta.glob` 로 읽는다 — node:fs 불필요, vitest 에서도 동일하게 동작.
 */

const REQUESTS = import.meta.glob<{ default: unknown }>("./requests/*.json", {
  eager: true,
});
const RESPONSES = import.meta.glob<{ default: unknown }>("./responses/*.json", {
  eager: true,
});

/** glob 키("./requests/full_pipeline.json") → 시나리오 이름("full_pipeline") */
function nameOf(globKey: string): string {
  return globKey.replace(/^.*\//, "").replace(/\.json$/, "");
}

function byName(mods: Record<string, { default: unknown }>): Map<string, unknown> {
  const map = new Map<string, unknown>();
  for (const [key, mod] of Object.entries(mods)) {
    map.set(nameOf(key), mod.default);
  }
  return map;
}

const requestMap = byName(REQUESTS);
const responseMap = byName(RESPONSES);

/** `requests/` 에 있는 모든 시나리오 이름 (정렬됨). */
export function listScenarios(): string[] {
  return [...requestMap.keys()].sort();
}

/** 시나리오의 요청 페이로드(AgentInput 모양). 항상 존재해야 한다. */
export function loadRequest(name: string): unknown {
  if (!requestMap.has(name)) throw new Error(`요청 fixture 없음: ${name}`);
  return requestMap.get(name);
}

/** 캡처된 실제 백엔드 응답. 아직 안 채워졌으면 null. */
export function loadResponse(name: string): unknown | null {
  return responseMap.has(name) ? responseMap.get(name) ?? null : null;
}
