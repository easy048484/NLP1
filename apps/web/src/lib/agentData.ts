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
/** 배열이면 그대로, {id: item} 형태의 dict면 값들만 뽑아 배열로 (id 키는 버림 —
 * 각 item 안에 자기 id가 이미 있다는 전제, decedent_estate.requirements가 이 모양). */
function asArrayOrRecordValues(v: unknown): unknown[] {
  if (Array.isArray(v)) return v;
  const rec = asRecord(v);
  return rec ? Object.values(rec) : [];
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

/**
 * 네임스페이스(data[agent].key)를 최상위 평면 키보다 우선해서 찾는다.
 * 오케스트레이터가 여러 에이전트의 data 를 dict.update() 로 합칠 때
 * 최상위 평면 키는 나중에 실행된 에이전트 값으로 덮어써질 수 있으므로
 * (병합 버그, 백엔드 팀 공유됨) 그 값에 기대면 안 되는 필드에 사용한다.
 * 네임스페이스 어디에도 없을 때만 최상위로 폴백한다.
 */
function deepFindNamespaceFirst(data: Record<string, unknown>, key: string): unknown {
  for (const v of Object.values(data)) {
    const rec = asRecord(v);
    if (rec && key in rec) return rec[key];
  }
  if (key in data) return data[key];
  return undefined;
}

/**
 * agentKey가 있으면 다른 agent의 namespace로는 절대 새지 않는다 — 후보
 * key들(우선순위 순) 중 자기 namespace(data[agentKey])에서 먼저 찾고,
 * 없으면 평면(top-level) 키로만 폴백한다(다른 agent namespace 순회 금지).
 * agentKey가 없을 때(legacy 호출)만 기존 deepFind처럼 아무 namespace나
 * 순회해서 찾는다. (#59/#63과 동일 원칙 — parsePendingQuestions 참고)
 */
function deepFindScoped(
  data: Record<string, unknown>,
  agentKey: string | undefined,
  ...keys: string[]
): unknown {
  if (agentKey) {
    const own = asRecord(data[agentKey]);
    if (own) {
      for (const k of keys) {
        if (k in own) return own[k];
      }
    }
    for (const k of keys) {
      if (k in data) return data[k];
    }
    return undefined;
  }
  for (const k of keys) {
    const v = deepFind(data, k);
    if (v !== undefined) return v;
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
  // decedent_estate.requirements[rid].grade 는 대문자만 쓴다(WHITE=간인 같은
  // 법정 요건 아닌 참고 항목, PENDING=확인 대기) — requirements가 dict라
  // 파싱이 항상 실패해오던 동안은(아래 parseSignals 참고) 드러나지 않았다.
  WHITE: "gray",
  PENDING: "pending",
};

const GRADE_BADGE: Record<SignalGrade, string> = {
  green: "충족",
  red: "확인 안 됨",
  yellow: "쟁점",
  gray: "참고",
  pending: "확인 대기",
};

export function parseSignals(
  data: Record<string, unknown>,
  agentKey?: string,
): RequirementSignal[] | null {
  // guide/signals는 배열 형태만 지원한다 — 지금 실제로 오는 건 requirements뿐이고,
  // decedent_estate.requirements는 {id: item} dict라 asArray()로는 항상 빈 배열이
  // 됐다(카드가 한 번도 렌더되지 않은 원인). requirements만 dict/array 둘 다 받는다.
  const guideOrSignals = asArray(deepFindScoped(data, agentKey, "guide", "signals"));
  const list = guideOrSignals.length
    ? guideOrSignals
    : asArrayOrRecordValues(deepFindScoped(data, agentKey, "requirements"));
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
  agentKey?: string,
): PendingQuestion[] | null {
  // agentKey가 있으면 다른 agent의 namespace로는 절대 새지 않는다 — 자기
  // namespace에 없으면 평면(top-level) 키로만 폴백한다(다른 agent namespace
  // 순회 금지). agentKey가 없을 때만(legacy 호출) 기존처럼 첫 namespace를
  // 순회하는 deepFindNamespaceFirst를 쓴다.
  const raw = agentKey
    ? (() => {
        const ownNamespace = asRecord(data[agentKey]);
        return (
          (ownNamespace && (ownNamespace.pending_questions ?? ownNamespace.questions)) ??
          data.pending_questions ??
          data.questions
        );
      })()
    : deepFindNamespaceFirst(data, "pending_questions") ?? deepFindNamespaceFirst(data, "questions");
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

/** 이 data 에 후속 질문(선택지)이 들어있는지. */
export function hasPendingQuestions(data: Record<string, unknown>, agentKey?: string): boolean {
  return (parsePendingQuestions(data, agentKey) ?? []).length > 0;
}

/**
 * 백엔드 tax_calculator/models.py `InheritanceTaxResult` 의 flat 필드 →
 * 내역 테이블 행. 라벨은 presentation.py `result_reply` 와 같은 표현으로 맞춰
 * 본문 답변과 카드가 같은 말을 쓰게 한다. 최종세액(estimated_tax_due)은 행이
 * 아니라 final_amount 로 따로 나간다.
 * ⚠️ 라벨·행 구성은 승원 확인 대상 (표시 결정).
 */
const TAX_ROW_FIELDS: readonly [string, string][] = [
  ["total_inherited_property", "상속재산 전체 금액"],
  ["deductible_expenses", "빚과 인정되는 비용"],
  ["taxable_inheritance_value", "세금 계산에 반영되는 재산"],
  ["total_inheritance_deduction", "공제되는 금액"],
  ["inheritance_tax_base", "세금을 매기는 기준 금액"],
  ["calculated_inheritance_tax", "세율을 적용해 계산한 세금"],
  ["filing_tax_credit", "기한 내 신고로 줄어드는 금액"],
];

function taxRowsFrom(rec: Record<string, unknown>): { label: string; amount: number }[] {
  // 1) 이미 rows/breakdown/items 로 오면 그대로 (미래 계약 대비)
  const rowsRaw = rec.rows ?? rec.breakdown ?? rec.items;
  if (Array.isArray(rowsRaw)) {
    return rowsRaw
      .map((r) => {
        const rr = asRecord(r);
        const label = asString(rr?.label);
        const amount = asNumber(rr?.amount ?? rr?.value);
        return label && amount != null ? { label, amount } : null;
      })
      .filter((r): r is { label: string; amount: number } => !!r);
  }
  const map = asRecord(rowsRaw);
  if (map) {
    return Object.entries(map)
      .map(([label, v]) => {
        const amount = asNumber(v);
        return amount != null ? { label, amount } : null;
      })
      .filter((r): r is { label: string; amount: number } => !!r);
  }
  // 2) 실제 백엔드: flat named 필드에서 알려진 것만 골라 순서대로
  return TAX_ROW_FIELDS.map(([field, label]) => {
    const amount = asNumber(rec[field]);
    return amount != null ? { label, amount } : null;
  }).filter((r): r is { label: string; amount: number } => !!r);
}

export function parseTaxResult(
  data: Record<string, unknown>,
  agentKey?: string,
): TaxResult | null {
  const raw = deepFindScoped(data, agentKey, "last_result", "tax_result", "result");
  const rec = asRecord(raw);
  if (!rec) return null;

  const rows = taxRowsFrom(rec);
  if (rows.length === 0) return null;

  // status 는 last_result 가 아니라 부모 state 에 있다 (state["status"]).
  const statusRaw =
    asString(deepFindScoped(data, agentKey, "status")) ?? asString(rec.status) ?? "calculated";
  return {
    status:
      statusRaw === "collecting" ||
      statusRaw === "unsupported" ||
      statusRaw === "needs_review"
        ? statusRaw
        : "calculated",
    rows,
    final_amount:
      asNumber(
        rec.estimated_tax_due ?? rec.final_amount ?? rec.final ?? rec.total,
      ) ??
      rows[rows.length - 1]?.amount ??
      null,
    filing_due:
      asString(rec.estimated_filing_deadline ?? rec.filing_due ?? rec.due_date) ?? null,
    notes: asArray(rec.warnings ?? rec.notes)
      .map((n) => asString(n))
      .filter((n): n is string => !!n),
  };
}

export function parsePlan(data: Record<string, unknown>): AgentPlan | null {
  const raw = deepFind(data, "plan");
  const rec = asRecord(raw);
  if (!rec) return null;

  // 백엔드 heir_navigator 의 ProcedurePlan 은 "timeline"(TimelineEntry: step/
  // title/summary/status)으로 온다. 예전 가정이던 "steps"/"tasks" 도 계속 받는다.
  const rawSteps = asArray(
    rec.timeline ?? rec.steps ?? rec.tasks,
  );
  const steps = rawSteps.map((s, i) => {
    const sr = asRecord(s) ?? {};
    return {
      id: asString(sr.id ?? sr.step) ?? `step-${i}`,
      title: asString(sr.title ?? sr.label ?? sr.name) ?? `할 일 ${i + 1}`,
      detail: asString(sr.detail ?? sr.description ?? sr.summary) ?? null,
      day_offset: asNumber(sr.day_offset ?? sr.day) ?? null,
      official_period: asString(sr.official_period ?? sr.period) ?? null,
      done: sr.done === true || sr.status === "done",
    };
  });

  // 백엔드 DeadlineItem: label / due_date / law(=근거) / base_label ...
  const deadlines = asArray(rec.deadlines).map((d) => {
    const dr = asRecord(d) ?? {};
    return {
      label: asString(dr.label ?? dr.name) ?? "기한",
      due_date: asString(dr.due_date ?? dr.date) ?? null,
      basis: asString(dr.basis ?? dr.note ?? dr.law) ?? null,
    };
  });

  if (steps.length === 0 && deadlines.length === 0) return null;
  return {
    steps,
    deadlines,
    next_action:
      asString(rec.next_action) ??
      (asArray(rec.next_actions).length > 0
        ? asString(asRecord(asArray(rec.next_actions)[0])?.title) ?? null
        : null),
    calendar_ics: asString(rec.calendar_ics ?? deepFind(data, "calendar_ics")) ?? null,
  };
}

/** heir_share_analyzer: 분배표 한 행. */
export interface ShareRow {
  heir: string;
  /** 법정상속분 (비율 문자열, 예 "3/7") */
  statutory: string;
  /** 유류분율 (비율 문자열, 예 "1/2") */
  forced?: string | null;
}

/**
 * 상속인 목록의 실제 위치: 백엔드 HeirShareResult 는 `last_result.heirs`
 * (HeirShareBreakdown[]) 에 담는다. 평면 heirs/shares/distribution 도 폴백.
 */
function shareList(data: Record<string, unknown>, agentKey: string | undefined): unknown[] {
  const lr = asRecord(deepFindScoped(data, agentKey, "last_result", "result"));
  if (lr && Array.isArray(lr.heirs)) return lr.heirs;
  return asArray(deepFindScoped(data, agentKey, "heirs", "shares", "distribution"));
}

export function parseShares(data: Record<string, unknown>, agentKey?: string): ShareRow[] | null {
  const list = shareList(data, agentKey);
  if (list.length === 0) return null;
  const rows: ShareRow[] = [];
  for (const r of list) {
    const rr = asRecord(r);
    if (!rr) continue;
    const heir = asString(rr.name ?? rr.heir ?? rr.relation);
    if (!heir) continue;
    rows.push({
      heir,
      // HeirShareBreakdown.statutory_share_fraction (구 계약: statutory_share/share)
      statutory:
        asString(rr.statutory_share_fraction ?? rr.statutory_share ?? rr.statutory ?? rr.share) ??
        "—",
      // HeirShareBreakdown.forced_share_rate_fraction.
      // ⚠️ 승원 확인: 유류분 칸에 비율(1/2) 대신 금액을 보여주려면
      //    basic_forced_share_estimate(원, estate 값 없으면 0)로 바꾼다.
      forced:
        asString(rr.forced_share_rate_fraction ?? rr.forced_share ?? rr.forced) ?? null,
    });
  }
  return rows.length ? rows : null;
}
