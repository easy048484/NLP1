/**
 * 에이전트 `data` 딕셔너리에서 카드 렌더용 구조를 관대하게(있으면 파싱, 없으면
 * null) 추출한다. 백엔드가 아직 최종 형태가 아니어도 화면이 안 깨지도록.
 */
import type {
  AgentPlan,
  PendingQuestion,
  RequirementSignal,
  SignalGrade,
  TaxResult,
} from "../types";

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}
function asArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}
function asString(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}
function asNumber(v: unknown): number | undefined {
  return typeof v === "number" && !Number.isNaN(v) ? v : undefined;
}

/** data 안 어디든(네임스페이스 키 포함) 특정 키를 찾는다. */
function deepFind(data: Record<string, unknown>, key: string): unknown {
  if (key in data) return data[key];
  for (const v of Object.values(data)) {
    const rec = asRecord(v);
    if (rec && key in rec) return rec[key];
  }
  return undefined;
}

const GRADE_MAP: Record<string, SignalGrade> = {
  green: "green",
  red: "red",
  yellow: "yellow",
  gray: "gray",
  grey: "gray",
  pending: "pending",
  GREEN: "green",
  RED: "red",
  YELLOW: "yellow",
};

const GRADE_BADGE: Record<SignalGrade, string> = {
  green: "충족",
  red: "확인 안 됨",
  yellow: "쟁점",
  gray: "참고",
  pending: "확인 대기",
};

export function parseSignals(data: Record<string, unknown>): RequirementSignal[] | null {
  const raw = deepFind(data, "guide") ?? deepFind(data, "signals") ?? deepFind(data, "requirements");
  const list = asArray(raw);
  if (list.length === 0) return null;

  const signals: RequirementSignal[] = [];
  for (const item of list) {
    const rec = asRecord(item);
    if (!rec) continue;
    const gradeRaw = asString(rec.grade ?? rec.signal ?? rec.status) ?? "gray";
    const grade = GRADE_MAP[gradeRaw] ?? "gray";
    const name = asString(rec.name ?? rec.requirement ?? rec.label) ?? "요건";
    const body =
      asString(rec.body ?? rec.instruction ?? rec.mistake_sentence ?? rec.note) ?? "";
    const precedents = asArray(rec.precedents ?? rec.precedent_cards)
      .map((p) => {
        const pr = asRecord(p);
        if (!pr) return null;
        return {
          case_no: asString(pr.case_no ?? pr.case_number ?? pr.id) ?? "",
          summary: asString(pr.summary ?? pr.gist ?? pr.text) ?? "",
        };
      })
      .filter((p): p is { case_no: string; summary: string } => !!p && !!p.case_no);
    signals.push({
      id: asString(rec.id) ?? name,
      name,
      grade,
      badge: asString(rec.badge) ?? GRADE_BADGE[grade],
      body,
      precedents: precedents.length ? precedents : undefined,
    });
  }
  return signals.length ? signals : null;
}

export function parsePendingQuestions(
  data: Record<string, unknown>,
): PendingQuestion[] | null {
  const raw = deepFind(data, "pending_questions") ?? deepFind(data, "questions");
  const list = asArray(raw);
  if (list.length === 0) return null;
  const out: PendingQuestion[] = [];
  for (const item of list) {
    const rec = asRecord(item);
    if (!rec) continue;
    const question = asString(rec.question);
    if (!question) continue;
    out.push({
      requirement: asString(rec.requirement) ?? "",
      field: asString(rec.field) ?? "",
      question,
      options: asArray(rec.options)
        .map((o) => {
          const or = asRecord(o);
          if (!or) return null;
          return {
            label: asString(or.label) ?? asString(or.value) ?? "",
            value: asString(or.value) ?? asString(or.label) ?? "",
          };
        })
        .filter((o): o is { label: string; value: string } => !!o && !!o.label),
    });
  }
  return out.length ? out : null;
}

export function parseTaxResult(data: Record<string, unknown>): TaxResult | null {
  const raw =
    deepFind(data, "last_result") ?? deepFind(data, "tax_result") ?? deepFind(data, "result");
  const rec = asRecord(raw);
  if (!rec) return null;

  // rows: [{label, amount}] 또는 {label: amount} 맵
  let rows: { label: string; amount: number }[] = [];
  const rowsRaw = rec.rows ?? rec.breakdown ?? rec.items;
  if (Array.isArray(rowsRaw)) {
    rows = rowsRaw
      .map((r) => {
        const rr = asRecord(r);
        const label = asString(rr?.label);
        const amount = asNumber(rr?.amount ?? rr?.value);
        return label && amount != null ? { label, amount } : null;
      })
      .filter((r): r is { label: string; amount: number } => !!r);
  } else {
    const map = asRecord(rowsRaw);
    if (map) {
      rows = Object.entries(map)
        .map(([label, v]) => {
          const amount = asNumber(v);
          return amount != null ? { label, amount } : null;
        })
        .filter((r): r is { label: string; amount: number } => !!r);
    }
  }
  if (rows.length === 0) return null;

  const statusRaw = asString(rec.status) ?? "calculated";
  return {
    status:
      statusRaw === "collecting" ||
      statusRaw === "unsupported" ||
      statusRaw === "needs_review"
        ? statusRaw
        : "calculated",
    rows,
    final_amount:
      asNumber(rec.final_amount ?? rec.final ?? rec.total) ?? rows[rows.length - 1]?.amount ?? null,
    filing_due: asString(rec.filing_due ?? rec.due_date) ?? null,
    notes: asArray(rec.notes)
      .map((n) => asString(n))
      .filter((n): n is string => !!n),
  };
}

export function parsePlan(data: Record<string, unknown>): AgentPlan | null {
  const raw = deepFind(data, "plan");
  const rec = asRecord(raw);
  if (!rec) return null;
  const steps = asArray(rec.steps ?? rec.tasks).map((s, i) => {
    const sr = asRecord(s) ?? {};
    return {
      id: asString(sr.id) ?? `step-${i}`,
      title: asString(sr.title ?? sr.label ?? sr.name) ?? `할 일 ${i + 1}`,
      detail: asString(sr.detail ?? sr.description) ?? null,
      day_offset: asNumber(sr.day_offset ?? sr.day) ?? null,
      official_period: asString(sr.official_period ?? sr.period) ?? null,
      done: sr.done === true,
    };
  });
  const deadlines = asArray(rec.deadlines).map((d) => {
    const dr = asRecord(d) ?? {};
    return {
      label: asString(dr.label ?? dr.name) ?? "기한",
      due_date: asString(dr.due_date ?? dr.date) ?? null,
      basis: asString(dr.basis ?? dr.note) ?? null,
    };
  });
  if (steps.length === 0 && deadlines.length === 0) return null;
  return {
    steps,
    deadlines,
    next_action: asString(rec.next_action) ?? null,
    calendar_ics: asString(rec.calendar_ics ?? deepFind(data, "calendar_ics")) ?? null,
  };
}

/** heir_share_analyzer: 분배표 [{heir, statutory_share, forced_share?}] */
export interface ShareRow {
  heir: string;
  statutory: string;
  forced?: string | null;
}
export function parseShares(data: Record<string, unknown>): ShareRow[] | null {
  const raw = deepFind(data, "shares") ?? deepFind(data, "distribution");
  const list = asArray(raw);
  if (list.length === 0) return null;
  const rows: ShareRow[] = [];
  for (const r of list) {
    const rr = asRecord(r);
    if (!rr) continue;
    const heir = asString(rr.heir ?? rr.name ?? rr.relation);
    if (!heir) continue;
    rows.push({
      heir,
      statutory: asString(rr.statutory_share ?? rr.statutory ?? rr.share) ?? "—",
      forced: asString(rr.forced_share ?? rr.forced) ?? null,
    });
  }
  return rows.length ? rows : null;
}
