import type { AgentInput, AgentOutput } from "../types";

export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";

export interface ChatCallResult {
  /** 실제로 서버에 전송한 요청 본문 (개발자 모드 JSON 뷰어용) */
  request: AgentInput;
  /** 서버가 돌려준 원본 응답. 실패 시 null */
  response: AgentOutput | null;
  ok: boolean;
  status: number | null;
  errorMessage: string | null;
  latencyMs: number;
}

/**
 * apps/api/main.py 의 POST /chat 을 호출합니다.
 * (AgentInput -> AgentOutput, apps/api/schemas/agent_io.py 참고)
 *
 * family_graph / family_graph_id는 이 프로토타입에서는 아직 다루지 않는
 * Phase 2(가족관계 그래프) 영역이라 보내지 않습니다 — 보내지 않으면
 * 오케스트레이터가 그대로 비워서 처리합니다 (orchestrator/router.py
 * node_build_context 참고).
 */
export async function sendChatMessage(
  sessionId: string,
  userMessage: string,
): Promise<ChatCallResult> {
  const request: AgentInput = {
    session_id: sessionId,
    user_message: userMessage,
    context: {},
  };

  const startedAt = performance.now();

  try {
    const res = await fetch(`${API_BASE_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });

    const latencyMs = Math.round(performance.now() - startedAt);
    let json: unknown = null;

    try {
      json = await res.json();
    } catch {
      json = null;
    }

    if (!res.ok) {
      const detail =
        json !== null && typeof json === "object" && "detail" in json
          ? JSON.stringify((json as { detail: unknown }).detail)
          : `HTTP ${res.status}`;

      return {
        request,
        response: null,
        ok: false,
        status: res.status,
        errorMessage: detail,
        latencyMs,
      };
    }

    return {
      request,
      response: json as AgentOutput,
      ok: true,
      status: res.status,
      errorMessage: null,
      latencyMs,
    };
  } catch (err) {
    const latencyMs = Math.round(performance.now() - startedAt);

    return {
      request,
      response: null,
      ok: false,
      status: null,
      errorMessage:
        err instanceof Error
          ? err.message
          : "알 수 없는 오류로 서버에 연결하지 못했습니다.",
      latencyMs,
    };
  }
}
