import { agentMeta } from "../../lib/agents";
import type { AgentName } from "../../types";

/** 원형 에이전트 아바타 (이모지 + 에이전트색). 대화에서 "누가 응답 중인지" 보여준다. */
export function AgentAvatar({
  agent,
  size = "md",
  pulse = false,
}: {
  agent: AgentName | string;
  size?: "sm" | "md" | "lg";
  pulse?: boolean;
}) {
  const meta = agentMeta(agent);
  return (
    <span
      className={`agent-avatar agent-avatar-${size}${pulse ? " agent-avatar-pulse" : ""}`}
      style={pulse ? undefined : { color: `var(${meta.colorVar})` }}
      aria-hidden="true"
    >
      {meta.emoji}
    </span>
  );
}
