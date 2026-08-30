import type {
  AgentInput,
  AgentOutput,
  ChatResponse,
  ConsultAxis,
} from "../types";
import { authHeader } from "./auth";

export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";

export interface ChatCallResult {
  /** 실제로 서버에 전송한 요청 본문 (개발자 모드 JSON 뷰어용) */
  request: AgentInput;
  /** 정규화된 합성 응답. 실패 시 null */
  response: ChatResponse | null;
  /** 서버가 돌려준 원본 JSON (개발자 모드용) */
  raw: unknown;
  ok: boolean;
  status: number | null;
  errorMessage: string | null;
  latencyMs: number;
}

/**
 * 백엔드가 이미 최종 계약(`ChatResponse`)을 반환하면 그대로 쓰고,
 * 아직 과도기라 단일 `AgentOutput`만 반환하면 1-contribution 짜리
 * `ChatResponse`로 감싼다 — 화면 코드는 항상 `ChatResponse`만 본다.
 */
export function normalizeChatResponse(raw: unknown): ChatResponse | null {
  if (raw === null || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;

  // 최종 계약: contributions[] 가 있음
  if (Array.isArray(obj.contributions)) {
    return {
      reply: typeof obj.reply === "string" ? obj.reply : "",
      needs_review: obj.needs_review === true,
      contributions: obj.contributions as AgentOutput[],
      plan: (obj.plan as ChatResponse["plan"]) ?? null,
      financial_profile:
        (obj.financial_profile as ChatResponse["financial_profile"]) ?? null,
      family_graph: (obj.family_graph as ChatResponse["family_graph"]) ?? null,
      primary_agent:
        (obj.primary_agent as ChatResponse["primary_agent"]) ??
        ((obj.contributions as AgentOutput[])[0]?.agent ?? null),
    };
  }

  // 과도기: 단일 AgentOutput
  if (typeof obj.agent === "string" && typeof obj.reply === "string") {
    const single = obj as unknown as AgentOutput;
    const plan =
      single.data && typeof single.data === "object" && "plan" in single.data
        ? ((single.data as Record<string, unknown>).plan as ChatResponse["plan"])
        : null;
    return {
      reply: single.reply,
      needs_review: single.needs_review === true,
      contributions: [single],
      plan: plan ?? null,
      financial_profile: null,
      family_graph: null,
      primary_agent: single.agent,
    };
  }

  return null;
}

/**
 * apps/api/main.py 의 POST /chat 을 호출합니다.
 *
 * familyGraphId가 있으면 요청에 실어 보냅니다 — 오케스트레이터가 이 id로
 * family_graph를 자동 조회해 채워주므로 프론트는 id만 들고 다니면 됩니다.
 * axis는 온보딩 "상담 구분"에서 정한 값(pre_need/post_death)입니다.
 */
export async function sendChatMessage(
  sessionId: string,
  userMessage: string,
  opts?: { familyGraphId?: string | null; axis?: ConsultAxis | null },
): Promise<ChatCallResult> {
  const request: AgentInput = {
    session_id: sessionId,
    user_message: userMessage,
    context: {},
    ...(opts?.familyGraphId ? { family_graph_id: opts.familyGraphId } : {}),
    ...(opts?.axis ? { axis: opts.axis } : {}),
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
        raw: json,
        ok: false,
        status: res.status,
        errorMessage: detail,
        latencyMs,
      };
    }

    const response = normalizeChatResponse(json);
    return {
      request,
      response,
      raw: json,
      ok: response !== null,
      status: res.status,
      errorMessage: response === null ? "응답 형식을 이해하지 못했습니다." : null,
      latencyMs,
    };
  } catch (err) {
    const latencyMs = Math.round(performance.now() - startedAt);
    return {
      request,
      response: null,
      raw: null,
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
