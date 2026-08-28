import type { AgentName } from "../types";

export interface AgentMeta {
  name: AgentName;
  label: string;
  shortLabel: string;
  description: string;
  color: string;
  bg: string;
  emoji: string;
  /** 백엔드에 껍데기(stub)만 등록된 에이전트. 라우팅은 되지만 "준비 중" 응답을 낸다. */
  stub?: boolean;
}

/**
 * apps/api/schemas/agent_io.py 의 AgentName enum 및 각 에이전트의
 * agents/<이름>/spec.py 선언과 맞춘 메타데이터입니다. 새 에이전트를 백엔드에
 * 등록하면 여기에도 한 항목을 추가해야 합니다 (AgentName 유니온 타입이 강제). 라벨/설명 문구는
 * README 및 각 에이전트 모듈 docstring의 담당 영역 설명을 따랐습니다.
 */
export const AGENTS: Record<AgentName, AgentMeta> = {
  heir_navigator: {
    name: "heir_navigator",
    label: "상속인 절차 내비게이터",
    shortLabel: "절차 안내",
    description: "상속 절차를 단계별로 안내해드려요",
    color: "#2563eb",
    bg: "#eff6ff",
    emoji: "🧭",
  },
  decedent_estate: {
    name: "decedent_estate",
    label: "유언장 · 자산정리 점검",
    shortLabel: "유언장 점검",
    description: "유언장 요건과 자산정리를 점검해드려요",
    color: "#7c3aed",
    bg: "#f5f3ff",
    emoji: "📜",
  },
  tax_calculator: {
    name: "tax_calculator",
    label: "상속세 계산",
    shortLabel: "세금 계산",
    description: "예상 상속세를 계산해드려요",
    color: "#059669",
    bg: "#ecfdf5",
    emoji: "🧮",
  },
  retirement_planner: {
    name: "retirement_planner",
    label: "은퇴자금 설계",
    shortLabel: "은퇴 설계",
    description: "은퇴까지 필요한 자금과 준비 갭을 계산해드려요",
    color: "#d97706",
    bg: "#fffbeb",
    emoji: "🏖️",
    stub: true,
  },
  asset_organizer: {
    name: "asset_organizer",
    label: "자산 목록 정리",
    shortLabel: "자산 정리",
    description: "보유 자산과 부채를 한눈에 정리해드려요",
    color: "#0891b2",
    bg: "#ecfeff",
    emoji: "🗂️",
    stub: true,
  },
};

export const AGENT_LIST: AgentMeta[] = [
  AGENTS.heir_navigator,
  AGENTS.decedent_estate,
  AGENTS.tax_calculator,
  AGENTS.retirement_planner,
  AGENTS.asset_organizer,
];
