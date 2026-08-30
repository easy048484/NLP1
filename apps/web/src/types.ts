/**
 * 백엔드 계약과 1:1로 맞춘 프론트엔드 타입.
 *
 * 대상은 기획서의 **최종 오케스트레이터 계약**입니다 (플래너: classify →
 * build_plan → execute_plan → compose → verify_numbers). `/chat` 응답은
 * 단일 `AgentOutput`이 아니라 합성 답변(`ChatResponse`)이며, 기여한
 * 에이전트별 원문/데이터가 `contributions[]`로 함께 옵니다.
 *
 * 백엔드가 아직 단일 `AgentOutput`만 반환하는 과도기에는 lib/api.ts의
 * `normalizeChatResponse`가 그것을 1-contribution 짜리 `ChatResponse`로
 * 감싸므로, 화면 코드는 언제나 `ChatResponse`만 다루면 됩니다.
 */

export type AgentName =
  | "heir_navigator"
  | "heir_share_analyzer"
  | "decedent_estate"
  | "tax_calculator"
  | "asset_organizer"
  // 데모 비핵심 — 백엔드엔 라우팅 가능하나 FunctionRail·데모 시나리오엔 안 뜸.
  | "retirement_planner";

/** 상담 축 — 온보딩 "상담 구분"에서 정하고 오케스트레이터 classify 힌트로 전달. */
export type ConsultAxis = "pre_need" | "post_death";

export interface AgentInput {
  session_id: string;
  user_message: string;
  family_graph?: Record<string, unknown> | null;
  family_graph_id?: string | null;
  /** "지금 준비 중"(pre_need) / "가족을 떠나보낸 뒤"(post_death) */
  axis?: ConsultAxis | null;
  context: Record<string, unknown>;
  /** 판독할 이미지의 base64 (유언장 사진, 안심상속 조회결과 캡처 등). */
  image_base64?: string | null;
  /** image_base64 의 MIME 타입 (예: image/jpeg). */
  image_media_type?: string | null;
}

export interface AgentOutput {
  agent: AgentName;
  reply: string;
  next_action?: string | null;
  data: Record<string, unknown>;
  /** verify_numbers 가 이 기여의 숫자를 원문과 대조하지 못함 */
  needs_review?: boolean;
}

/** heir_navigator 의 data["plan"] — "할 일 타임라인" 렌더용. */
export interface PlanStep {
  id: string;
  title: string;
  detail?: string | null;
  /** 상속개시일 기준 며칠째 (표시용). */
  day_offset?: number | null;
  /** 공식 처리기간 배지 문구 (예: "금융·부동산 7일"). */
  official_period?: string | null;
  done?: boolean;
}

export interface PlanDeadline {
  label: string;
  /** ISO date */
  due_date?: string | null;
  basis?: string | null;
}

export interface AgentPlan {
  steps: PlanStep[];
  deadlines: PlanDeadline[];
  next_action?: string | null;
  /** RFC 5545 텍스트 — 다운로드 버튼으로 제공. */
  calendar_ics?: string | null;
}

/** decedent_estate 의 유언 요건 신호등 한 줄. 스펙: 요건판정_문구_스펙_v1.md */
export type SignalGrade = "green" | "red" | "yellow" | "gray" | "pending";

export interface RequirementSignal {
  id: string;
  /** 요건명 (예: "주소") */
  name: string;
  grade: SignalGrade;
  /** 배지 라벨 (예: "충족" / "확인 안 됨" / "쟁점" / "참고" / "확인 대기") */
  badge: string;
  /** 본문 설명 — 스펙 §3-2 문구 패턴 그대로 */
  body: string;
  precedents?: PrecedentRef[];
}

export interface PrecedentRef {
  /** 사건번호 (예: "2012다71688") */
  case_no: string;
  /** 요지 한 줄 */
  summary: string;
}

/** pending_questions() 항목 — 프론트가 선택 버튼을 그리도록 설계됨. */
export interface PendingQuestion {
  requirement: string;
  field: string;
  question: string;
  options: { label: string; value: string }[];
}

/** tax_calculator 의 data["last_result"] — 세액 8항목 내역. */
export interface TaxBreakdownRow {
  label: string;
  amount: number;
}

export interface TaxResult {
  status: "collecting" | "calculated" | "unsupported" | "needs_review";
  rows: TaxBreakdownRow[];
  /** 최종 예상 상속세 */
  final_amount?: number | null;
  /** 예상 신고기한 (ISO date) */
  filing_due?: string | null;
  notes?: string[];
}

/**
 * 세션 공유 상속재산 요약 — 백엔드 flat FinancialProfile
 * (real_estate_value / financial_assets / other_assets / total_debts)에서
 * 프론트가 패널에 쓸 만큼만 뽑아낸 것. asset_organizer 가 채운다.
 */
export interface EstateSummary {
  totalAssets: number;
  totalDebts: number;
  net: number;
}

/**
 * decedent_estate 가 판정한 유언장 상태 요약 — 백엔드 WillStatus.
 * checked=true 일 때만 의미가 있다.
 */
export interface WillStatus {
  checked: boolean;
  will_type?: string | null;
  no_will: boolean;
  overall_grade?: "green" | "yellow" | "red" | null;
  has_effect?: boolean | null;
}

/** `/chat` 의 최종 응답. */
export interface ChatResponse {
  /** compose 된 최종 답변 (마크다운) */
  reply: string;
  /** verify_numbers 실패 → "확인 필요" 배지 */
  needs_review: boolean;
  /** 이번 턴에 기여한 에이전트별 원문 + data */
  contributions: AgentOutput[];
  plan?: AgentPlan | null;
  /** 백엔드 flat FinancialProfile 에서 뽑은 재산 요약 */
  estate?: EstateSummary | null;
  /** 백엔드 WillStatus (decedent_estate 판정) */
  will_status?: WillStatus | null;
  family_graph?: FamilyGraphOut | null;
  /** 하위호환: 과도기 단일 에이전트 응답에서 채워짐 */
  primary_agent?: AgentName | null;
}

/**
 * 백엔드 apps/api/family_graph/schemas.py / models.py 와 1:1.
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
  /** 대습상속: 먼저 사망한 자녀의 사망일 (ISO date) */
  deceased_date?: string | null;
}

/** 보낸 필드만 갱신하는 부분 수정 요청. */
export interface FamilyMemberPatch {
  name?: string;
  relation?: RelationType;
  is_alive?: boolean;
  is_minor?: boolean;
  deceased_date?: string | null;
}

export interface FamilyMemberOut {
  id: number;
  name: string;
  relation: RelationType;
  is_alive: boolean;
  is_minor: boolean;
  deceased_date?: string | null;
}

export interface FamilyGraphOut {
  id: string;
  created_at: string;
  members: FamilyMemberOut[];
}

/**
 * 백엔드 apps/api/auth/schemas.py 의 UserOut / TokenOut 과 1:1.
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
