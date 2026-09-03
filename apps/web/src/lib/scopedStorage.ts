/**
 * 로그인 여부에 따라 저장 위치가 달라지는 브라우저 저장소.
 *
 * 왜 나눴나
 * ---------
 * 비로그인 사용자가 입력한 가족정보·사망일은 "대화창을 떠나면 남지 않는다"가
 * 원칙입니다. 그런데 지금까지는 family_graph_id 같은 값을 전부 localStorage에
 * 넣어서, 브라우저를 닫았다 열어도 그대로 복원됐습니다. 서버 쪽 행도 함께
 * 남아 있었으므로(정리 배치가 없었음) 사실상 영구 보관이었습니다.
 *
 *   비로그인 → sessionStorage : 탭을 닫으면 사라집니다. 새로고침은 견디므로
 *                               상담 도중 실수로 새로고침해도 대화가 유지됩니다.
 *   로그인   → localStorage   : 다음 방문에 이어서 씁니다.
 *
 * 서버도 같은 기준으로 갈립니다 — sessions.user_id 가 NULL이면 2시간 뒤
 * 정리 배치가 행을 지우고, 값이 있으면 30일 보관합니다
 * (apps/api/orchestrator/session_store.py).
 *
 * 프라이빗 브라우징 등 저장소 접근이 막힌 환경에서도 앱이 죽지 않도록 모든
 * 접근을 try/catch로 감쌉니다 — 실패하면 그냥 복원이 안 될 뿐입니다.
 */

import { TOKEN_KEY } from "./auth";

/** 이 모듈이 관리하는 키 전부. 로그인 승격·로그아웃 정리가 이 목록을 씁니다. */
export const SCOPED_KEYS = [
  "nlp1.session_id",
  "nlp1.family_graph_id",
  "nlp1.family_graph_intake_progress",
  "nlp1.family_graph_intake_answers",
  "eznext.consult_axis",
] as const;

export const SESSION_ID_KEY = "nlp1.session_id";

function safeGet(store: Storage | null, key: string): string | null {
  try {
    return store?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function safeSet(store: Storage | null, key: string, value: string): void {
  try {
    store?.setItem(key, value);
  } catch {
    /* 저장 실패해도 이번 세션은 메모리 state로 계속 진행합니다. */
  }
}

function safeRemove(store: Storage | null, key: string): void {
  try {
    store?.removeItem(key);
  } catch {
    /* ignore */
  }
}

function local(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function ephemeral(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** 지금 로그인 상태인지. 토큰이 있으면 값을 오래 보관해도 되는 사용자입니다. */
function isSignedIn(): boolean {
  return safeGet(local(), TOKEN_KEY) !== null;
}

/**
 * 값을 읽습니다. 로그인 저장소를 먼저 보고, 없으면 비로그인 저장소를 봅니다.
 *
 * 순서가 중요합니다 — 비로그인으로 쓰던 값이 sessionStorage에 남아 있는 채로
 * 로그인하면, 승격(promoteScopedKeys) 이후에는 localStorage 쪽이 정답입니다.
 */
export function readScoped(key: string): string | null {
  return safeGet(local(), key) ?? safeGet(ephemeral(), key);
}

/** 지금 스코프에 씁니다. 반대쪽에 남은 값은 지워서 둘이 어긋나지 않게 합니다. */
export function writeScoped(key: string, value: string): void {
  if (isSignedIn()) {
    safeSet(local(), key, value);
    safeRemove(ephemeral(), key);
  } else {
    safeSet(ephemeral(), key, value);
    safeRemove(local(), key);
  }
}

/** 양쪽 저장소에서 지웁니다. */
export function clearScoped(key: string): void {
  safeRemove(local(), key);
  safeRemove(ephemeral(), key);
}

/**
 * 로그인 직후 호출합니다. 비로그인으로 쓰던 값을 그대로 계정 저장소로 옮겨,
 * 대화창을 떠나지 않고 로그인한 사용자가 하던 상담을 이어갈 수 있게 합니다.
 */
export function promoteScopedKeys(): void {
  for (const key of SCOPED_KEYS) {
    const value = safeGet(ephemeral(), key);
    if (value === null) continue;
    safeSet(local(), key, value);
    safeRemove(ephemeral(), key);
  }
}

/** 로그아웃 시 호출합니다. 이 앱이 남긴 값을 양쪽 저장소에서 모두 지웁니다. */
export function clearAllScopedKeys(): void {
  for (const key of SCOPED_KEYS) clearScoped(key);
}
