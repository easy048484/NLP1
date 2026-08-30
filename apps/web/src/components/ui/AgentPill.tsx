import { agentMeta } from "../../lib/agents";
import type { AgentName } from "../../types";

/** 합성 답변 문단 앞 / 에이전트 스트립에 붙는 에이전트 라벨. */
export function AgentPill({
  agent,
  variant = "short",
}: {
  agent: AgentName | string;
  variant?: "short" | "full";
}) {
  const meta = agentMeta(agent);
  return (
    <span
      className="agent-pill"
      style={{
        color: `var(${meta.colorVar})`,
        background: `var(${meta.bgVar})`,
      }}
    >
      <span aria-hidden="true">{meta.emoji}</span>
      {variant === "full" ? meta.label : meta.shortLabel}
    </span>
  );
}
