import type { AgentName } from "../types";

export interface AgentMeta {
  name: AgentName;
  label: string;
  shortLabel: string;
  description: string;
  color: string;
  bg: string;
  emoji: string;
}

/**
 * apps/api/schemas/agent_io.py 의 AgentName enum, orchestrator/router.py 의
 * _KEYWORD_ROUTES 와 맞춘 3개 에이전트 메타데이터입니다. 라벨/설명 문구는
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
};

export const AGENT_LIST: AgentMeta[] = [
  AGENTS.heir_navigator,
  AGENTS.decedent_estate,
  AGENTS.tax_calculator,
];
