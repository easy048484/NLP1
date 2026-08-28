/**
 * 회원가입·로그인 클라이언트.
 *
 * 가족관계 그래프·자산 정보 같은 민감한 개인정보를 다루므로, 앱은 로그인한
 * 사용자만 쓸 수 있습니다(App.tsx가 토큰이 없으면 AuthScreen을 띄움).
 *
 * 토큰과 사용자 정보는 localStorage에 보관합니다 — 새로고침해도 로그인이
 * 유지되도록. 프라이빗 브라우징 등 접근이 막힌 환경에서도 앱이 죽지 않게
 * 모든 접근을 try/catch로 감쌉니다(그 경우 새로고침하면 다시 로그인).
 */

import type { AuthResponse, AuthUser } from "../types";
import { API_BASE_URL } from "./api";

const TOKEN_KEY = "nlp1.auth_token";
const USER_KEY = "nlp1.auth_user";

export interface StoredAuth {
  token: string;
  user: AuthUser;
}

export function getStoredAuth(): StoredAuth | null {
  try {
    const token = window.localStorage.getItem(TOKEN_KEY);
    const rawUser = window.localStorage.getItem(USER_KEY);
    if (!token || !rawUser) return null;
    return { token, user: JSON.parse(rawUser) as AuthUser };
  } catch {
    return null;
  }
}

function persist(auth: AuthResponse): StoredAuth {
  const stored: StoredAuth = { token: auth.access_token, user: auth.user };
  try {
    window.localStorage.setItem(TOKEN_KEY, stored.token);
    window.localStorage.setItem(USER_KEY, JSON.stringify(stored.user));
  } catch {
    // 저장 실패해도 이번 세션은 메모리 state로 진행합니다.
  }
  return stored;
}

export function clearAuth(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(USER_KEY);
  } catch {
    // ignore
  }
}

/** fetch 헤더에 얹을 Authorization. 토큰이 없으면 빈 객체. */
export function authHeader(): Record<string, string> {
  const stored = getStoredAuth();
  return stored ? { Authorization: `Bearer ${stored.token}` } : {};
}

export interface AuthResult {
  ok: boolean;
  auth: StoredAuth | null;
  /** 사용자에게 그대로 보여줄 한글 오류 메시지 (실패 시). */
  errorMessage: string | null;
}

async function post(path: string, body: unknown): Promise<AuthResult> {
  try {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    let json: unknown = null;
    try {
      json = await res.json();
    } catch {
      json = null;
    }

    if (!res.ok) {
      return { ok: false, auth: null, errorMessage: readDetail(json, res.status) };
    }
    return { ok: true, auth: persist(json as AuthResponse), errorMessage: null };
  } catch (err) {
    return {
      ok: false,
      auth: null,
      errorMessage:
        err instanceof Error
          ? "서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요."
          : "알 수 없는 오류가 발생했어요.",
    };
  }
}

/** FastAPI 오류 응답(detail)을 사람이 읽을 문장으로 바꿉니다. */
function readDetail(json: unknown, status: number): string {
  if (json && typeof json === "object" && "detail" in json) {
    const detail = (json as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    // pydantic 검증 오류는 배열 형태 — 첫 메시지만 꺼내 보여줍니다.
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: string };
      if (first.msg) return first.msg.replace(/^Value error, /, "");
    }
  }
  if (status === 401) return "이메일 또는 비밀번호가 올바르지 않습니다.";
  if (status === 409) return "이미 가입된 이메일입니다.";
  return `요청을 처리하지 못했어요. (HTTP ${status})`;
}

export function register(
  email: string,
  password: string,
  name: string,
): Promise<AuthResult> {
  return post("/auth/register", { email, password, name });
}

export function login(email: string, password: string): Promise<AuthResult> {
  return post("/auth/login", { email, password });
}

export function logout(): void {
  clearAuth();
}
