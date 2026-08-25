import type { AgentInput, AgentOutput, FamilyTreeIn, FamilyTreeOut } from "../types";

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
 * familyGraphId가 있으면 매 요청에 실어 보냅니다 — 세션도 기억해주지만
 * 세션 TTL(2시간)이 지나면 잊어버리므로, 프론트가 localStorage에 들고
 * 있다가 항상 함께 보내는 쪽이 안전합니다.
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

/**
 * 가족 트리 저장/조회 (apps/api/family_graph/router.py).
 * 온보딩 화면(FamilySetup)이 씁니다. 실패 시 Error를 던지므로 호출부가
 * try/catch로 에러 문구를 보여줘야 합니다.
 */

async function familyTreeRequest(
  path: string,
  init?: RequestInit,
): Promise<FamilyTreeOut> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body.detail) detail = JSON.stringify(body.detail);
    } catch {
      // 본문이 JSON이 아니면 상태 코드만 보여줍니다.
    }
    throw new Error(detail);
  }
  return (await res.json()) as FamilyTreeOut;
}

export function createFamilyTree(tree: FamilyTreeIn): Promise<FamilyTreeOut> {
  return familyTreeRequest("/family-graph", {
    method: "POST",
    body: JSON.stringify(tree),
  });
}

export function getFamilyTree(familyGraphId: string): Promise<FamilyTreeOut> {
  return familyTreeRequest(`/family-graph/${familyGraphId}`);
}

export function updateFamilyTree(
  familyGraphId: string,
  tree: FamilyTreeIn,
): Promise<FamilyTreeOut> {
  return familyTreeRequest(`/family-graph/${familyGraphId}`, {
    method: "PUT",
    body: JSON.stringify(tree),
  });
}
