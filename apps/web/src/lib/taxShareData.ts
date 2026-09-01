/** 상속세·유류분 카드: 백엔드가 계산한 값만 표시용으로 매핑한다. */
import type { TaxResult } from "../types";
import { formatWonExact } from "./format";

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function amount(value: unknown): number | undefined {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : undefined;
}

function optionalAmount(value: unknown): number | null | undefined {
  return value == null ? null : amount(value);
}

function notes(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => text(item) !== undefined)
    : [];
}

function date(value: unknown): string | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
    ? value
    : null;
}

/** 기본 입력은 flatten된 data. 이전 단일 응답도 자기 namespace만 읽는다. */
function ownData(data: Record<string, unknown>, target: string, agentKey?: string) {
  if (agentKey && agentKey !== target) return null;
  if (target in data) return record(data[target]);
  return data;
}

const TAX_ROWS = [
  ["total_inherited_property", "총상속재산"],
  ["deductible_expenses", "차감 비용"],
  ["taxable_inheritance_value", "상속세 과세가액"],
  ["total_inheritance_deduction", "상속공제 합계"],
  ["inheritance_tax_base", "과세표준"],
  ["calculated_inheritance_tax", "산출세액"],
  ["filing_tax_credit", "신고세액공제"],
  ["estimated_tax_due", "최종 예상 상속세"],
] as const;

const REQUIRED_TAX_AMOUNTS = [
  "total_inherited_property",
  "inheritance_tax_base",
  "calculated_inheritance_tax",
  "filing_tax_credit",
  "estimated_tax_due",
];

export function parseTaxResult(
  data: Record<string, unknown>,
  agentKey?: string,
): TaxResult | null {
  const state = ownData(data, "tax_calculator", agentKey);
  if (!state) return null;

  if ("last_result" in state) {
    // status는 last_result 안이 아닌 에이전트 상태에 있다. 미완료의 이전 세액은 숨긴다.
    if (state.status !== "calculated") return null;
    const result = record(state.last_result);
    if (!result || REQUIRED_TAX_AMOUNTS.some((field) => amount(result[field]) === undefined)) {
      return null;
    }
    return {
      status: "calculated",
      rows: TAX_ROWS.flatMap(([field, label]) => {
        const value = amount(result[field]);
        return value === undefined ? [] : [{ label, amount: value }];
      }),
      final_amount: amount(result.estimated_tax_due),
      filing_due: date(result.estimated_filing_deadline),
      notes: notes(result.warnings),
    };
  }

  // 기존 UI용 result/rows 응답만 호환한다. 명시적인 last_result:null을 우회하지 않는다.
  const result = record(state.tax_result ?? state.result);
  if (!result || (state.status ?? result.status ?? "calculated") !== "calculated") return null;
  const raw = result.rows ?? result.breakdown ?? result.items;
  const rows = Array.isArray(raw)
    ? raw.flatMap((item) => {
        const row = record(item);
        const label = text(row?.label);
        const value = amount(row?.amount ?? row?.value);
        return label && value !== undefined ? [{ label, amount: value }] : [];
      })
    : Object.entries(record(raw) ?? {}).flatMap(([label, value]) => {
        const parsed = amount(value);
        return parsed === undefined ? [] : [{ label, amount: parsed }];
      });
  if (!rows.length) return null;
  return {
    status: "calculated",
    rows,
    final_amount:
      amount(result.final_amount ?? result.final ?? result.total) ??
      rows[rows.length - 1]?.amount ??
      null,
    filing_due: date(result.filing_due ?? result.due_date),
    notes: notes(result.notes),
  };
}

export interface ShareRow {
  heir: string;
  statutory: string;
  forced?: string | null;
  relation?: string;
  statutory_share_fraction?: string;
  statutory_share_amount?: number;
  forced_share_rate_fraction?: string;
  basic_forced_share_estimate?: number;
  planned_acquisition?: number | null;
  simple_gap?: number | null;
}

const SHARE_STATUSES = new Set([
  "basic_estimate",
  "no_simple_gap",
  "possible_gap",
  "expert_review_required",
]);

function shareResult(state: Record<string, unknown>): Record<string, unknown> | null {
  const result = record(state.last_result);
  if (
    !result ||
    !SHARE_STATUSES.has(String(state.status)) ||
    result.status !== state.status
  ) return null;
  // 미지원·입력 오류 응답에 지난 턴 결과가 남아 있더라도 표를 재사용하지 않는다.
  if (state.last_error || text(state.asked_slot)) return null;
  if (Array.isArray(state.missing_fields) && state.missing_fields.length > 0) return null;
  return result;
}

function fraction(value: unknown): string | undefined {
  return typeof value === "string" && /^\d+(?:\/[1-9]\d*)?$/.test(value) ? value : undefined;
}

export function parseShares(data: Record<string, unknown>, agentKey?: string): ShareRow[] | null {
  const state = ownData(data, "heir_share_analyzer", agentKey);
  if (!state) return null;
  if ("last_result" in state) {
    const result = shareResult(state);
    if (!result || !Array.isArray(result.heirs) || !result.heirs.length) return null;
    const rows: ShareRow[] = [];
    for (const item of result.heirs) {
      const heir = record(item);
      if (!heir) return null;
      const name = text(heir.name);
      const relation = text(heir.relation);
      const statutory = fraction(heir.statutory_share_fraction);
      const statutoryAmount = amount(heir.statutory_share_amount);
      const rate = fraction(heir.forced_share_rate_fraction);
      const basicAmount = amount(heir.basic_forced_share_estimate);
      const planned = optionalAmount(heir.planned_acquisition);
      const gap = optionalAmount(heir.simple_gap);
      // 일부 상속인을 조용히 누락한 표는 만들지 않는다. 계산·추정으로 값을 보충하지 않는다.
      if (
        !name || !relation || !statutory || !rate ||
        statutoryAmount === undefined || basicAmount === undefined ||
        planned === undefined || gap === undefined
      ) return null;
      rows.push({
        heir: name,
        relation,
        statutory: `${statutory} · ${formatWonExact(statutoryAmount)}`,
        forced: `법정상속분의 ${rate} · ${formatWonExact(basicAmount)}`,
        statutory_share_fraction: statutory,
        statutory_share_amount: statutoryAmount,
        forced_share_rate_fraction: rate,
        basic_forced_share_estimate: basicAmount,
        planned_acquisition: planned,
        simple_gap: gap,
      });
    }
    return rows;
  }
  const raw = state.shares ?? state.distribution;
  if (!Array.isArray(raw)) return null;
  if (state.status !== undefined && !SHARE_STATUSES.has(String(state.status))) return null;
  const rows = raw.flatMap((item) => {
    const row = record(item);
    const name = text(row?.heir ?? row?.name ?? row?.relation);
    return name
      ? [{
          heir: name,
          statutory: text(row?.statutory_share ?? row?.statutory ?? row?.share) ?? "—",
          forced: text(row?.forced_share ?? row?.forced) ?? null,
        }]
      : [];
  });
  return rows.length ? rows : null;
}

export function parseShareWarnings(data: Record<string, unknown>, agentKey?: string): string[] {
  const state = ownData(data, "heir_share_analyzer", agentKey);
  const result = state && shareResult(state);
  return result ? notes(result.warnings) : [];
}
