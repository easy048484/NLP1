/**
 * 에이전트 `data` 딕셔너리에서 카드 렌더용 구조를 관대하게(있으면 파싱, 없으면
 * null) 추출한다. 백엔드가 아직 최종 형태가 아니어도 화면이 안 깨지도록.
 */
import type {
  AgentPlan,
  PendingQuestion,
  RequirementSignal,
  SignalGrade,
} from "../types";

export { parseTaxResult, parseShares, parseShareWarnings } from "./taxShareData";
export type { ShareRow } from "./taxShareData";

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

/**
 * asset_organizer는 구조화된 pending_questions를 안 주고 대신 pending_categories
 * (문자열 배열)와 안내 문구만 준다 — "나머지는 없어요"를 직접 타이핑하지
 * 않아도 되게, 이 배열이 있으면 선택지 1개짜리 PendingQuestion을 합성한다.
 * field는 일부러 비워둔다 — asset_organizer는 구조화 context가 아니라
 * 평문 "나머지는 없어요"를 사용자 발화로 받아야 _is_negative_answer()가
 * 인식한다(ChoiceGroup은 field가 없으면 평문만 보낸다).
 */
function assetOrganizerPendingQuestion(
  ownNamespace: Record<string, unknown> | null,
): PendingQuestion | null {
  const categories = asArray(ownNamespace?.pending_categories).filter(
    (c): c is string => typeof c === "string" && c.length > 0,
  );
  if (categories.length === 0) return null;
  return {
    requirement: "",
    field: "",
    question: `아직 말씀 안 하신 항목이 있어요: ${categories.join(", ")}. 있으면 알려주시고, 없으면 아래에서 선택해주세요.`,
    options: [{ label: "나머지는 없어요", value: "나머지는 없어요" }],
  };
}

export interface AssetAmountRequest {
  /** 백엔드 pending_amounts 항목 kind — 후속 메시지 문구 조립에만 쓴다. */
  kind: "asset_value" | "liability_value" | "insurance_value";
  /** 되묻는 대상 카테고리 이름 (예: "예금", "대출", "보험"). */
  label: string;
}

/**
 * asset_organizer가 특정 카테고리의 금액을 되묻는 중인지(state.pending_amounts
 * 첫 항목) 확인한다. 백엔드는 이 항목이 있으면 그 금액 질문만 reply로 보내고
 * pending_categories는 비워두므로(agent.py._continue_after_categories 참고),
 * 두 종류의 후속 질문은 항상 서로 배타적이다 — 이 항목이 있으면 카테고리
 * 선택지(assetOrganizerPendingQuestion) 대신 금액 입력 위젯을 렌더해야 한다.
 */
export function parseAssetAmountRequest(
  data: Record<string, unknown>,
  agentKey?: string,
): AssetAmountRequest | null {
  if (!agentKey) return null;
  const ownNamespace = asRecord(data[agentKey]);
  const pendingAmounts = asArray(ownNamespace?.pending_amounts);
  if (pendingAmounts.length === 0) return null;
  const first = asRecord(pendingAmounts[0]);
  if (!first) return null;
  const kind = asString(first.kind);
  if (
    kind !== "asset_value" &&
    kind !== "liability_value" &&
    kind !== "insurance_value"
  ) {
    return null;
  }
  const label = asString(
    kind === "liability_value" ? first.liability_type : first.asset_type,
  );
  if (!label) return null;
  return { kind, label };
}

/** 이 data 에 asset_organizer 금액 되묻기(pending_amounts)가 있는지. */
export function hasAssetAmountRequest(
  data: Record<string, unknown>,
  agentKey?: string,
): boolean {
  return parseAssetAmountRequest(data, agentKey) !== null;
}

/**
 * asset_organizer가 자산정리 시작 의사만 있고 구체적인 자산 항목이 없어
 * (예: "자산 정리하고 싶어요") 카테고리 선택 UI로 진입시키는 중인지
 * (state.awaiting_category_selection) 확인한다. 이 플래그는 이번 턴
 * 응답에만 실리는 신호다(agent.py의 _empty_state() 키 목록에 없어 다음
 * 턴에 다시 로드되지 않음) — pending_amounts/pending_categories와 달리
 * 대화 상태로 지속되지 않는다.
 */
export function hasCategorySelectionRequest(
  data: Record<string, unknown>,
  agentKey?: string,
): boolean {
  if (!agentKey) return false;
  const ownNamespace = asRecord(data[agentKey]);
  return ownNamespace?.awaiting_category_selection === true;
}

export interface RemainingCategoriesPrompt {
  /** 아직 확인 안 된 카테고리(백엔드 state.pending_categories 그대로). */
  categories: string[];
}

/**
 * 선택 항목 입력이 끝난 뒤 남은 미확인 카테고리를 한 번에 확인하는
 * 단계(state.pending_categories)를 읽는다. assetOrganizerPendingQuestion과
 * 같은 소스를 읽지만, 이쪽은 "네 모두 없어요"/"더 있어요" 두 버튼 UI
 * (RemainingCategoriesPrompt 컴포넌트)를 위해 카테고리 배열 자체를
 * 그대로 넘긴다 — 문구 조립은 컴포넌트가 한다.
 */
export function parseRemainingCategoriesPrompt(
  data: Record<string, unknown>,
  agentKey?: string,
): RemainingCategoriesPrompt | null {
  if (!agentKey) return null;
  const ownNamespace = asRecord(data[agentKey]);
  const categories = asArray(ownNamespace?.pending_categories).filter(
    (c): c is string => typeof c === "string" && c.length > 0,
  );
  if (categories.length === 0) return null;
  return { categories };
}

export function parsePendingQuestions(
  data: Record<string, unknown>,
  agentKey?: string,
): PendingQuestion[] | null {
  // agentKey가 있으면 다른 agent의 namespace로는 절대 새지 않는다 — 자기
  // namespace에 없으면 평면(top-level) 키로만 폴백한다(다른 agent namespace
  // 순회 금지). agentKey가 없을 때만(legacy 호출) 기존처럼 첫 namespace를
  // 순회하는 deepFindNamespaceFirst를 쓴다.
  if (agentKey) {
    const ownNamespace = asRecord(data[agentKey]);
    const synthesized = assetOrganizerPendingQuestion(ownNamespace);
    if (synthesized) return [synthesized];
  }
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
