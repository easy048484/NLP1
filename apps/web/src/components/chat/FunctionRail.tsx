import { useApp } from "../../lib/appState";
import { AgentAvatar } from "../ui";
import type { AgentName } from "../../types";

/**
 * 에이전트가 제공하는 "기능" 타일. 대화창을 여는 대신, 하고 싶은 일을 고르면
 * 담당 에이전트가 그 작업을 단계별로 안내한다. 상담 화면 상단에 상시 노출.
 */
interface AgentFunction {
  key: string;
  agent: AgentName;
  name: string;
  blurb: string;
  prompt: string;
  axis?: "pre_need" | "post_death";
}

const AGENT_FUNCTIONS: AgentFunction[] = [
  {
    key: "asset",
    agent: "asset_organizer",
    name: "자산 정리",
    blurb: "예금·보험·부동산·연금을 한눈에 모으고 은퇴 자금을 점검",
    prompt: "가진 자산을 정리하고 싶어요",
    axis: "pre_need",
  },
  {
    key: "will",
    agent: "decedent_estate",
    name: "유언 요건 점검",
    blurb: "유언장의 형식 요건을 판례에 비춰 항목별로 확인",
    prompt: "유언장 형식 요건을 점검하고 싶어요",
  },
  {
    key: "tax",
    agent: "tax_calculator",
    name: "상속세 시산",
    blurb: "재산·채무와 공제를 반영한 예상 세액을 단계별로",
    prompt: "상속세가 얼마나 나올지 계산해 주세요",
  },
  {
    key: "procedure",
    agent: "heir_navigator",
    name: "상속 절차 안내",
    blurb: "사망신고·기한·서류를 순서대로, 할 일 목록으로",
    prompt: "상속 절차를 처음부터 안내해 주세요",
    axis: "post_death",
  },
  {
    key: "share",
    agent: "heir_share_analyzer",
    name: "법정상속분 · 유류분",
    blurb: "누가 얼마를 받는지, 유류분 격차는 어느 정도인지",
    prompt: "법정상속분과 유류분을 계산해 주세요",
    axis: "post_death",
  },
];

export function FunctionRail() {
  const { turns, axis, send, loading } = useApp();

  const engaged = new Set(
    turns
      .filter((t) => t.role === "assistant" && t.response)
      .flatMap((t) => t.response!.contributions.map((c) => c.agent)),
  );

  const fns = AGENT_FUNCTIONS.filter((f) => !f.axis || f.axis === axis);

  return (
    <div className="fn-rail" role="group" aria-label="에이전트 기능">
      {fns.map((f) => {
        const active = engaged.has(f.agent);
        return (
          <button
            key={f.key}
            type="button"
            className={`fn-tile${active ? " fn-tile-active" : ""}`}
            disabled={loading}
            onClick={() => void send(f.prompt)}
          >
            <span className="fn-tile-top">
              <AgentAvatar agent={f.agent} size="sm" />
              {active && <span className="fn-tile-status">진행 중</span>}
            </span>
            <span className="fn-tile-name">{f.name}</span>
            <span className="fn-tile-blurb">{f.blurb}</span>
          </button>
        );
      })}
    </div>
  );
}
