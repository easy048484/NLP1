import { AGENTS } from "../lib/agents";
import type { AgentName } from "../types";
import { DevPanel, type TurnDebugInfo } from "./DevPanel";

export interface Turn {
  id: string;
  role: "user" | "assistant";
  text: string;
  agent?: AgentName;
  isError?: boolean;
  debug?: TurnDebugInfo;
}

export function ChatMessage({ turn, devMode }: { turn: Turn; devMode: boolean }) {
  if (turn.role === "user") {
    return (
      <div className="msg-row msg-row-user">
        <div className="bubble bubble-user">{turn.text}</div>
      </div>
    );
  }

  const meta = turn.agent ? AGENTS[turn.agent] : null;

  return (
    <div className="msg-row msg-row-assistant">
      <div className="msg-assistant-col">
        {meta && !turn.isError && (
          <div className="agent-label" style={{ color: meta.color }}>
            <span>{meta.emoji}</span>
            <span>{meta.label}</span>
          </div>
        )}
        <div
          className={`bubble bubble-assistant${turn.isError ? " bubble-error" : ""}`}
          style={meta && !turn.isError ? { borderColor: `${meta.color}33` } : undefined}
        >
          {turn.text}
        </div>
        {devMode && turn.debug && <DevPanel debug={turn.debug} />}
      </div>
    </div>
  );
}
