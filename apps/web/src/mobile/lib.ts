/**
 * 모바일 간단 버전 공용 로직 — 진행 상태 저장(이어하기)과 에이전트 호출.
 *
 * PC 채팅과 세션을 섞지 않도록 모바일 전용 session_id 를 따로 둔다.
 * 계산·판정은 모두 /chat(에이전트)이 하고, 여기서는 입력을 구조화해 보낼 뿐이다.
 */
import { useCallback, useEffect, useState } from "react";
import { sendChatMessage } from "../lib/api";
import type { AgentOutput, ChatResponse, ConsultAxis } from "../types";

// ------------------------------------------------------------------ 저장

function readJson<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* 사생활 보호 모드 등 — 이어하기만 안 될 뿐 화면은 동작 */
  }
}

function newSessionId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `m-${crypto.randomUUID()}`;
  }
  return `m-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** 흐름별 진행 상태를 localStorage 에 보관한다 — 새로고침·재방문 시 이어하기. */
export function useFlowState<T extends { sessionId: string }>(
  key: string,
  initial: () => Omit<T, "sessionId">,
): [T, (patch: Partial<T>) => void, () => void] {
  const [state, setState] = useState<T>(
    () => readJson<T>(key) ?? ({ ...initial(), sessionId: newSessionId() } as T),
  );

  useEffect(() => {
    writeJson(key, state);
  }, [key, state]);

  const update = useCallback((patch: Partial<T>) => {
    setState((prev) => ({ ...prev, ...patch }));
  }, []);

  const reset = useCallback(() => {
    setState({ ...initial(), sessionId: newSessionId() } as T);
    // initial 은 호출부 상수 — 의존성에서 제외
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return [state, update, reset];
}

export const PREPARE_KEY = "eznext.m.prepare";
export const AFTER_KEY = "eznext.m.after";

/** 홈의 "이어서 하실까요?" 배너용 — 저장된 흐름의 마지막 단계만 읽는다. */
export function readSavedStep(key: string): string | null {
  const saved = readJson<{ step?: string }>(key);
  return saved?.step ?? null;
}

// ------------------------------------------------------------------ 가족

export interface Family {
  spouse: boolean;
  children: number;
}

export function heirNames(family: Family): string[] {
  const names: string[] = [];
  if (family.spouse) names.push("배우자");
  for (let i = 1; i <= family.children; i += 1) names.push(`자녀${i}`);
  return names;
}

/** 백엔드 classify_heirs 가 읽는 inline family_graph. */
export function familyGraph(family: Family): Record<string, unknown> {
  return {
    heirs: heirNames(family).map((name) => ({
      name,
      relation: name === "배우자" ? "spouse" : "child",
      alive: true,
      minor: false,
    })),
  };
}

/** 법정상속분(배우자 1.5 : 자녀 1)을 정수 %로 — 초기값 표시용. 합이 정확히 100이 되게 맞춘다. */
export function statutoryPercents(family: Family): Record<string, number> {
  const names = heirNames(family);
  if (names.length === 0) return {};
  const weights = names.map((n) => (n === "배우자" && family.children > 0 ? 1.5 : 1));
  const total = weights.reduce((a, b) => a + b, 0);
  const raw = weights.map((w) => Math.floor((w / total) * 100));
  let rest = 100 - raw.reduce((a, b) => a + b, 0);
  for (let i = 0; rest > 0; i = (i + 1) % raw.length, rest -= 1) raw[i] += 1;
  return Object.fromEntries(names.map((n, i) => [n, raw[i]]));
}

/**
 * 한 사람의 비율을 v 로 바꾸고, 나머지 사람은 기존 비율대로 나눠 합계를 100 으로 맞춘다.
 * (슬라이더용 — 합계가 100을 넘어 막히지 않게)
 */
export function rebalancePercents(
  percents: Record<string, number>,
  name: string,
  value: number,
): Record<string, number> {
  const v = Math.max(0, Math.min(100, Math.round(value)));
  const others = Object.keys(percents).filter((n) => n !== name);
  if (others.length === 0) return { [name]: 100 };
  const rest = 100 - v;
  const base = others.reduce((a, n) => a + (percents[n] ?? 0), 0);
  const raw = others.map((n) => (base > 0 ? ((percents[n] ?? 0) / base) * rest : rest / others.length));
  const floored = raw.map(Math.floor);
  let left = rest - floored.reduce((a, b) => a + b, 0);
  // 끝전은 소수점이 큰 사람부터 1%씩
  const order = raw.map((r, i) => [r - Math.floor(r), i] as const).sort((a, b) => b[0] - a[0]);
  for (let k = 0; left > 0; k = (k + 1) % order.length, left -= 1) floored[order[k][1]] += 1;
  const out: Record<string, number> = {};
  for (const n of Object.keys(percents)) out[n] = n === name ? v : floored[others.indexOf(n)];
  return out;
}

/** 비율(%)을 원 단위로 — 끝전은 마지막 사람에게 몰아 합계를 맞춘다. */
export function percentsToAmounts(
  percents: Record<string, number>,
  total: number,
): Record<string, number> {
  const names = Object.keys(percents);
  const out: Record<string, number> = {};
  let used = 0;
  names.forEach((name, i) => {
    const amount =
      i === names.length - 1 ? total - used : Math.floor((total * percents[name]) / 100);
    out[name] = Math.max(0, amount);
    used += out[name];
  });
  return out;
}

// ------------------------------------------------------------------ 에이전트 호출

export interface AgentCall {
  response: ChatResponse | null;
  error: string | null;
}

export async function askAgent(
  sessionId: string,
  message: string,
  opts: {
    axis: ConsultAxis;
    family?: Family | null;
    context?: Record<string, unknown>;
    image?: { base64: string; mediaType: string };
  },
): Promise<AgentCall> {
  const result = await sendChatMessage(sessionId, message, {
    axis: opts.axis,
    familyGraph: opts.family ? familyGraph(opts.family) : null,
    context: opts.context,
    image: opts.image,
  });
  if (!result.ok || !result.response) {
    return {
      response: null,
      error:
        result.status === 0
          ? "연결이 잠시 끊겼어요. 잠시 후 다시 시도해주세요."
          : "에이전트가 답을 만들지 못했어요. 다시 시도해주세요.",
    };
  }
  return { response: result.response, error: null };
}

/** 특정 에이전트의 기여(contribution)만 꺼낸다. */
export function contributionOf(
  response: ChatResponse | null | undefined,
  agent: string,
): AgentOutput | null {
  return response?.contributions.find((c) => c.agent === agent) ?? null;
}

/** 에이전트 data 에서 자기 namespace 를 우선으로 key 를 찾는다. */
export function agentField(output: AgentOutput | null, key: string): unknown {
  if (!output) return undefined;
  const own = output.data[output.agent];
  if (own && typeof own === "object" && key in (own as Record<string, unknown>)) {
    return (own as Record<string, unknown>)[key];
  }
  return output.data[key];
}

// ------------------------------------------------------------------ 표시

/** 상속인별 색 — 도넛·아바타 공용. 토큰만. */
export const HEIR_COLORS = [
  "var(--brand-gold)",
  "var(--brand-navy)",
  "var(--agent-share)",
  "var(--agent-asset)",
  "var(--agent-estate)",
  "var(--agent-tax)",
  "var(--agent-heir)",
];


const WON = new Intl.NumberFormat("ko-KR");

export function won(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `${WON.format(Math.round(n))}원`;
}

/** 1억 2,300만 원 식의 짧은 표기 (카드 요약용). */
export function wonShort(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const abs = Math.abs(Math.round(n));
  const eok = Math.floor(abs / 100_000_000);
  const man = Math.round((abs % 100_000_000) / 10_000);
  const parts: string[] = [];
  if (eok) parts.push(`${WON.format(eok)}억`);
  if (man) parts.push(`${WON.format(man)}만`);
  if (!parts.length) return `${WON.format(abs)}원`;
  return `${n < 0 ? "-" : ""}${parts.join(" ")} 원`;
}

export function todayIso(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

export function dateKo(iso: string | null | undefined): string {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return `${y}년 ${m}월 ${d}일`;
}

export function downloadText(filename: string, text: string, mime: string): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
