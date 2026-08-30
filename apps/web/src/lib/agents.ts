import type { AgentName } from "../types";

export interface AgentMeta {
  name: AgentName;
  /** 응답 헤더에 쓰는 정식 명칭 */
  label: string;
  /** 합성 답변 문단 pill / 에이전트 스트립에 쓰는 짧은 라벨 */
  shortLabel: string;
  description: string;
  /** CSS 변수명 (tokens.css) — 인라인 색 대신 var()로 참조 */
  colorVar: string;
  bgVar: string;
  emoji: string;
}

/**
 * 기획서 최종 상태의 전문 에이전트 5종.
 * (heir_navigator, heir_share_analyzer, decedent_estate, tax_calculator, asset_organizer)
 *
 * 색은 tokens.css의 --agent-* 변수를 가리킨다 — 다크모드/고대비에서
 * 자동으로 따라가도록.
 */
export const AGENTS: Record<AgentName, AgentMeta> = {
  heir_navigator: {
    name: "heir_navigator",
    label: "상속인 절차 안내",
    shortLabel: "절차 안내",
    description: "사망신고·안심상속 원스톱·한정승인·신고 기한을 순서대로 안내해요",
    colorVar: "--agent-heir",
    bgVar: "--agent-heir-bg",
    emoji: "🧭",
  },
  heir_share_analyzer: {
    name: "heir_share_analyzer",
    label: "법정상속분 · 유류분 분석",
    shortLabel: "상속분 분석",
    description: "민법 기준 법정상속분과 유류분을 계산해 분배를 정리해요",
    colorVar: "--agent-share",
    bgVar: "--agent-share-bg",
    emoji: "⚖️",
  },
  decedent_estate: {
    name: "decedent_estate",
    label: "유언 요건 점검",
    shortLabel: "유언 점검",
    description: "자필증서·녹음 유언의 형식 요건을 판례에 비춰 항목별로 확인해요",
    colorVar: "--agent-estate",
    bgVar: "--agent-estate-bg",
    emoji: "📜",
  },
  tax_calculator: {
    name: "tax_calculator",
    label: "상속세 시산",
    shortLabel: "상속세 시산",
    description: "등록된 가족을 반영해 재산·채무부터 예상 상속세를 계산해요",
    colorVar: "--agent-tax",
    bgVar: "--agent-tax-bg",
    emoji: "🧮",
  },
  asset_organizer: {
    name: "asset_organizer",
    label: "상속재산 정리",
    shortLabel: "재산 정리",
    description: "예금·보험·부동산·부채를 정리하고, 안심상속 조회 결과도 읽어요",
    colorVar: "--agent-asset",
    bgVar: "--agent-asset-bg",
    emoji: "🗂️",
  },
  // 데모 비핵심. 백엔드가 "은퇴/노후/연금" 발화에 라우팅할 수 있어 메타만 둔다.
  // AGENT_LIST(=FunctionRail)에는 넣지 않는다.
  retirement_planner: {
    name: "retirement_planner",
    label: "은퇴자금 설계",
    shortLabel: "은퇴 설계",
    description: "은퇴 시점까지 필요한 자금과 준비 자금의 갭을 추정해요",
    colorVar: "--agent-asset",
    bgVar: "--agent-asset-bg",
    emoji: "📈",
  },
};

export const AGENT_LIST: AgentMeta[] = [
  AGENTS.heir_navigator,
  AGENTS.heir_share_analyzer,
  AGENTS.decedent_estate,
  AGENTS.tax_calculator,
  AGENTS.asset_organizer,
];

/** 알 수 없는 에이전트 이름이 와도 화면이 안 깨지도록. */
export function agentMeta(name: AgentName | string | null | undefined): AgentMeta {
  if (name && name in AGENTS) return AGENTS[name as AgentName];
  return {
    name: "heir_navigator",
    label: "안내",
    shortLabel: "안내",
    description: "",
    colorVar: "--ink-muted",
    bgVar: "--surface-sunken",
    emoji: "•",
  };
}
