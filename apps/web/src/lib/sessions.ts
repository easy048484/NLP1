/**
 * 대화 세션 이어보기 클라이언트 (apps/api/orchestrator/session_api.py).
 *
 * 로그아웃하면 클라이언트가 session_id 를 버립니다. 서버에는 그 세션이 30일
 * 동안 남아 있는데 이름을 잊어버리니, 다시 로그인해도 대화가 처음부터
 * 시작됐습니다 — 가족관계는 /family-graph/mine 으로 되찾아지는데 대화 맥락만
 * 유실되는 비대칭이 있었습니다. 이 모듈이 그 비대칭을 없앱니다.
 */

import type { EstateSummary, WillStatus } from "../types";
import { API_BASE_URL, readEstate, readWillStatus } from "./api";
import { authHeader } from "./auth";

export interface ConversationTurn {
  role: "user" | "assistant";
  content: string;
}

export interface LatestSession {
  session_id: string;
  family_graph_id: string | null;
  /** '준비 현황' 패널용. 서버에 남아 있던 재산 요약 — 없으면 null. */
  estate: EstateSummary | null;
  will_status: WillStatus | null;
  history: ConversationTurn[];
}

/**
 * GET /sessions/mine — 로그인한 사용자의 가장 최근 대화.
 *
 * 이어볼 대화가 없으면(첫 로그인, 30일 경과) null 을 돌려줍니다. 실패도 null
 * 입니다 — 이어보기는 있으면 좋은 것이지 로그인 자체를 막을 이유가 아닙니다.
 */
export async function fetchLatestSession(): Promise<LatestSession | null> {
  try {
    const res = await fetch(`${API_BASE_URL}/sessions/mine`, {
      headers: { "Content-Type": "application/json", ...authHeader() },
    });
    if (!res.ok) return null;

    const json = (await res.json()) as Record<string, unknown>;
    if (typeof json?.session_id !== "string" || !json.session_id) return null;

    const history = Array.isArray(json.history) ? (json.history as unknown[]) : [];
    return {
      session_id: json.session_id,
      family_graph_id: typeof json.family_graph_id === "string" ? json.family_graph_id : null,
      // ChatResponse 와 같은 파서를 쓴다 — 응답 모양이 어긋나면 한 곳만 고치면 된다.
      estate: readEstate(json),
      will_status: readWillStatus(json),
      history: history.filter((turn): turn is ConversationTurn => {
        if (!turn || typeof turn !== "object") return false;
        const t = turn as Record<string, unknown>;
        return (t.role === "user" || t.role === "assistant") && typeof t.content === "string";
      }),
    };
  } catch {
    return null;
  }
}
