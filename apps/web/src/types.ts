/**
 * 백엔드 apps/api/schemas/agent_io.py 의 AgentInput / AgentOutput 계약과
 * 1:1로 맞춘 프론트엔드 타입입니다. 백엔드 스키마가 바뀌면 여기도 같이
 * 바꿔주세요 — 이 타입들이 개발자 모드의 요청/응답 JSON 뷰어와
 * 실제 fetch 호출 양쪽에서 공통으로 쓰입니다.
 */

export type AgentName =
  | "heir_navigator"
  | "decedent_estate"
  | "tax_calculator"
  | "heir_share_analyzer"
  | "retirement_planner"
  | "asset_organizer";

/** 세션 공유 재무 상태 — 백엔드 FinancialProfile. 모든 필드 선택. */
export interface FinancialProfile {
  real_estate_value?: number | null;
  financial_assets?: number | null;
  financial_debts?: number | null;
  other_assets?: number | null;
  total_debts?: number | null;
  current_age?: number | null;
  retirement_age?: number | null;
  monthly_income?: number | null;
  monthly_expense?: number | null;
  monthly_pension?: number | null;
  extra?: Record<string, unknown>;
}

export interface HandoffRequest {
  target: AgentName;
  reason?: string | null;
  priority: number;
}

/** compose 단계의 숫자·날짜 검증 결과. ok=false 면 "⚠️ 확인필요" 배지를 띄운다. */
export interface VerificationResult {
  ok: boolean;
  mode: "single" | "synthesized" | "concat" | "concat_after_failure";
  mismatches: string[];
}

export interface AgentInput {
  session_id: string;
  user_message: string;
  family_graph?: Record<string, unknown> | null;
  family_graph_id?: string | null;
  financial_profile?: FinancialProfile | null;
  context: Record<string, unknown>;
}

export interface AgentOutput {
  agent: AgentName;
  reply: string;
  next_action?: string | null;
  handoffs?: HandoffRequest[];
  financial_profile?: FinancialProfile | null;
  data: Record<string, unknown>;
}

/**
 * POST /chat 응답 — 백엔드 ChatResponse. AgentOutput 의 상위 호환으로,
 * 이번 턴에 실제 실행된 에이전트 목록과 경로 등급, 숫자 검증 결과가 붙는다.
 * `agent` 는 여러 개가 돌았을 때 DAG 의 마지막(대표) 에이전트다.
 */
export interface ChatResponse extends AgentOutput {
  agents: AgentName[];
  path: "fast" | "standard" | "full";
  verification?: VerificationResult | null;
}

/**
 * 백엔드 apps/api/family_graph/schemas.py / models.py 와 1:1로 맞춘 타입입니다.
 * (family_graph_입력_플로우_계획_0823.md 참고)
 */
export type RelationType =
  | "spouse"
  | "child"
  | "parent"
  | "grandchild"
  | "sibling"
  | "grandparent";

export interface FamilyMemberIn {
  name: string;
  relation: RelationType;
  is_alive?: boolean;
  is_minor?: boolean;
}

/** 보낸 필드만 갱신하는 부분 수정 요청 (PATCH /family-graph/{id}/members/{member_id}). */
export interface FamilyMemberPatch {
  name?: string;
  relation?: RelationType;
  is_alive?: boolean;
  is_minor?: boolean;
}

export interface FamilyMemberOut {
  id: number;
  name: string;
  relation: RelationType;
  is_alive: boolean;
  is_minor: boolean;
}

export interface FamilyGraphOut {
  id: string;
  created_at: string;
  members: FamilyMemberOut[];
}

/**
 * 백엔드 apps/api/auth/schemas.py 의 UserOut / TokenOut 과 1:1로 맞춘 타입입니다.
 */
export interface AuthUser {
  id: string;
  email: string;
  name: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}
