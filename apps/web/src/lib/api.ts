import type { AgentInput, AgentOutput } from "../types";
import { authHeader } from "./auth";

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
 * familyGraphId가 있으면 요청에 실어 보냅니다 — 오케스트레이터의
 * node_build_context가 이 id로 family_graph를 자동 조회해서 채워주므로
 * (family_graph_입력_플로우_계획_0823.md 1-1절), 프론트는 id만 들고
 * 다니면 됩니다. localStorage에 저장된 id를 읽어 넘기는 건 호출부
 * (App.tsx)의 책임입니다.
 */
export async function sendChatMessage(
  sessionId: string,
  userMessage: string,
  familyGraphId?: string | null,
): Promise<ChatCallResult> {
  const request: AgentInput = {
    session_id: sessionId,
    user_message: userMessage,
    context: {},
    ...(familyGraphId ? { family_graph_id: familyGraphId } : {}),
  };

  const startedAt = performance.now();

  try {
    const res = await fetch(`${API_BASE_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeader() },
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
