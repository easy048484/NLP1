import { AGENT_LIST } from "../lib/agents";
import type { AgentName } from "../types";

/**
 * 지금 어떤 에이전트가 응답 중인지 사용자가 한눈에 알 수 있도록 보여주는
 * 헤더 하단 표시줄. 오케스트레이터 라우팅 결과(AgentOutput.agent)로만
 * 갱신되며, 첫 메시지를 보내기 전까지는 활성 표시가 없습니다.
 */
export function AgentStrip({ active }: { active: AgentName | null }) {
  return (
    <div className="agent-strip">
      {AGENT_LIST.map((agent) => {
        const isActive = active === agent.name;
        return (
          <div
            key={agent.name}
            className={`agent-chip${isActive ? " agent-chip-active" : ""}`}
            style={
              isActive
                ? { borderColor: agent.color, background: agent.bg, color: agent.color }
                : undefined
            }
            title={agent.description}
          >
            <span aria-hidden="true">{agent.emoji}</span>
            <span>{agent.shortLabel}</span>
          </div>
        );
      })}
    </div>
  );
}
