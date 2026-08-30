import type {
  AgentInput,
  AgentName,
  AgentOutput,
  ChatResponse,
  ConsultAxis,
  EstateSummary,
  VerificationResult,
  WillStatus,
} from "../types";
import { parsePlan } from "./agentData";
import { authHeader } from "./auth";

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};
}

function asNum(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** 백엔드 ChatResponse.verification.ok === false → "⚠️ 확인필요" 배지 */
function readNeedsReview(obj: Record<string, unknown>): boolean {
  if (obj.needs_review === true) return true;
  const v = asRecord(obj.verification);
  return v.ok === false;
}

/** 백엔드 VerificationResult → 타입 있는 형태. 없으면 null. */
function readVerification(obj: Record<string, unknown>): VerificationResult | null {
  if (!obj.verification || typeof obj.verification !== "object") return null;
  const v = asRecord(obj.verification);
  return {
    ok: v.ok === true,
    mode: typeof v.mode === "string" ? v.mode : "",
    mismatches: Array.isArray(v.mismatches)
      ? v.mismatches.filter((m): m is string => typeof m === "string")
      : [],
  };
}

/**
 * 백엔드 node_compose(orchestrator/router.py)는 이번 턴 에이전트들의 data 를
 * 최상위에 평면 병합한다(`merged_data.update(o.data)`). 규약을 따르는 에이전트는
 * 자기 몫을 `data[<agent>]` 네임스페이스에도 함께 넣지만, 전환기라 아래 레거시
 * 평면 키도 같이 나온다. 화면(agentData.parse*)이 다른 에이전트 데이터를 주워
 * 담지 않도록, 에이전트별로 "자기 것"인 평면 키만 골라 슬라이스에 합쳐준다.
 */
const LEGACY_FLAT_KEYS: Partial<Record<AgentName, readonly string[]>> = {
  decedent_estate: [
    "will_type",
    "requirements",
    "guide",
    "warnings",
    "review",
    "pending_questions",
  ],
  heir_navigator: [
    "plan",
    "calendar_ics",
    "asked_slot",
    "handoff_reason",
    "pending_questions",
  ],
};

/**
 * `response.agents` 를 순회해 에이전트별 contribution 을 만든다.
 * - `data` 는 `rawData[agent]`(네임스페이스 슬라이스)를 기본으로 하고,
 *   그 위에 이 에이전트가 쓰는 레거시 평면 키만 덧씌운다(네임스페이스 값 우선).
 * - `reply` 는 빈 문자열 — 합성 답변은 ChatResponse.reply(최상위)에만 있고,
 *   카드 렌더(AgentCards)는 `contribution.data` 만 본다.
 *
 * ⚠️ pending_questions / handoff_reason 처럼 decedent_estate 와 heir_navigator 가
 *   같은 평면 키를 쓰면, 백엔드 평면 병합(merged_data.update) 때문에 마지막
 *   에이전트 값만 남고 나머지는 사라진다. 어느 에이전트 것이었는지 복원할 수
 *   없어서, 네임스페이스 슬라이스에 그 키가 없는 에이전트에는 살아남은 평면
 *   값을 그대로 채워 넣는다(= 두 에이전트가 같은 후속질문을 보게 될 수 있음).
 *   최소한 화면이 안 깨지게 하는 임시 처리이며, 후속 질문이 엉뚱한 에이전트
 *   카드에 붙을 수 있다.
 *   TODO(정민 확인 필요): node_compose 가 data 를 에이전트별 네임스페이스로만
 *   내려주도록 고치면 LEGACY_FLAT_KEYS 병합과 이 복사 로직을 통째로 제거.
 */
function splitContributions(
  agents: AgentName[],
  rawData: Record<string, unknown>,
): AgentOutput[] {
  const seen = new Set<AgentName>();
  const out: AgentOutput[] = [];
  for (const agent of agents) {
    if (seen.has(agent)) continue;
    seen.add(agent);

    const slice = asRecord(rawData[agent]);
    const data: Record<string, unknown> = { ...slice };
    for (const key of LEGACY_FLAT_KEYS[agent] ?? []) {
      if (key in rawData && !(key in data)) data[key] = rawData[key];
    }
    out.push({ agent, reply: "", data });
  }
  return out;
}

/** 백엔드 flat FinancialProfile → 패널용 재산 요약. 값이 하나도 없으면 null. */
function readEstate(obj: Record<string, unknown>): EstateSummary | null {
  const fp = asRecord(obj.financial_profile);
  const re = asNum(fp.real_estate_value);
  const fa = asNum(fp.financial_assets);
  const oa = asNum(fp.other_assets);
  const td = asNum(fp.total_debts);
  if (re === null && fa === null && oa === null && td === null) return null;
  const totalAssets = (re ?? 0) + (fa ?? 0) + (oa ?? 0);
  const totalDebts = td ?? 0;
  return { totalAssets, totalDebts, net: totalAssets - totalDebts };
}

/** 백엔드 WillStatus. checked 가 없으면(구버전/미점검) null. */
function readWillStatus(obj: Record<string, unknown>): WillStatus | null {
  const w = asRecord(obj.will_status);
  if (typeof w.checked !== "boolean") return null;
  const grade = w.overall_grade;
  return {
    checked: w.checked,
    will_type: typeof w.will_type === "string" ? w.will_type : null,
    no_will: w.no_will === true,
    overall_grade:
      grade === "green" || grade === "yellow" || grade === "red" ? grade : null,
    has_effect: typeof w.has_effect === "boolean" ? w.has_effect : null,
  };
}

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

function readAgents(obj: Record<string, unknown>): AgentName[] {
  return Array.isArray(obj.agents)
    ? obj.agents.filter((a): a is AgentName => typeof a === "string")
    : [];
}

function readPath(obj: Record<string, unknown>): string {
  return typeof obj.path === "string" ? obj.path : "standard";
}

/**
 * 백엔드 `/chat` 응답을 화면이 다루는 `ChatResponse` 모양으로 정규화한다.
 * - 최종 계약(`contributions[]`)을 이미 주면 그대로 쓴다.
 * - 현재 백엔드처럼 `agents[]` + 평면 병합 `data` 를 주면 agents 를 순회해
 *   에이전트별 contribution 으로 쪼갠다(splitContributions).
 * - 아주 옛 단일 `AgentOutput` 은 1-contribution 으로 감싼다.
 * 화면 코드는 언제나 `ChatResponse` 만 본다.
 */
export function normalizeChatResponse(raw: unknown): ChatResponse | null {
  if (raw === null || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;

  const agents = readAgents(obj);

  // 이미 최종 계약(contributions[]) 을 주는 백엔드 — 그대로 쓴다.
  if (Array.isArray(obj.contributions)) {
    const contributions = obj.contributions as AgentOutput[];
    return {
      reply: typeof obj.reply === "string" ? obj.reply : "",
      needs_review: readNeedsReview(obj),
      contributions,
      agents: agents.length > 0 ? agents : contributions.map((c) => c.agent),
      path: readPath(obj),
      verification: readVerification(obj),
      plan: parsePlan(obj),
      estate: readEstate(obj),
      will_status: readWillStatus(obj),
      family_graph: (obj.family_graph as ChatResponse["family_graph"]) ?? null,
      primary_agent:
        (obj.primary_agent as ChatResponse["primary_agent"]) ??
        (contributions[0]?.agent ?? null),
    };
  }

  // 현재 백엔드: ChatResponse = AgentOutput + {agents, path, verification,
  // financial_profile(flat), will_status}. 합성 data 는 obj.data 에 평면 병합돼
  // 있고, contributions[] 는 여기서 agents 를 순회해 만든다.
  const rawData = asRecord(obj.data);

  if (agents.length > 0) {
    return {
      reply: typeof obj.reply === "string" ? obj.reply : "",
      needs_review: readNeedsReview(obj),
      contributions: splitContributions(agents, rawData),
      agents,
      path: readPath(obj),
      verification: readVerification(obj),
      plan: parsePlan(rawData),
      estate: readEstate(obj),
      will_status: readWillStatus(obj),
      family_graph: (obj.family_graph as ChatResponse["family_graph"]) ?? null,
      primary_agent:
        (obj.agent as ChatResponse["primary_agent"]) ??
        (agents[agents.length - 1] ?? null),
    };
  }

  // agents 가 없는 아주 옛 백엔드: 단일 AgentOutput 을 1-contribution 으로 감싼다.
  if (typeof obj.agent === "string" && typeof obj.reply === "string") {
    const single = obj as unknown as AgentOutput;
    return {
      reply: single.reply,
      needs_review: readNeedsReview(obj),
      contributions: [single],
      agents: [single.agent],
      path: readPath(obj),
      verification: readVerification(obj),
      plan: parsePlan(asRecord(single.data)),
      estate: readEstate(obj),
      will_status: readWillStatus(obj),
      family_graph: (obj.family_graph as ChatResponse["family_graph"]) ?? null,
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
  opts?: {
    familyGraphId?: string | null;
    axis?: ConsultAxis | null;
    /** 선택 버튼 등에서 구조화 답변을 함께 보낼 때 (예: {will_type: "none"}) */
    context?: Record<string, unknown>;
    /** 유언장·안심상속 조회결과 사진 등. 서버가 판독 직후 폐기(저장 안 함). */
    image?: { base64: string; mediaType: string };
  },
): Promise<ChatCallResult> {
  const request: AgentInput = {
    session_id: sessionId,
    user_message: userMessage,
    context: opts?.context ?? {},
    ...(opts?.familyGraphId ? { family_graph_id: opts.familyGraphId } : {}),
    ...(opts?.axis ? { axis: opts.axis } : {}),
    ...(opts?.image
      ? {
          image_base64: opts.image.base64,
          image_media_type: opts.image.mediaType,
        }
      : {}),
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
