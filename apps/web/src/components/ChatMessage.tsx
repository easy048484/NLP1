import { AGENTS } from "../lib/agents";
import type { AgentName, VerificationResult } from "../types";
import { DevPanel, type TurnDebugInfo } from "./DevPanel";

export interface Turn {
  id: string;
  role: "user" | "assistant";
  text: string;
  agent?: AgentName;
  isError?: boolean;
  /** compose 검증 결과. ok=false 면 LLM 합성이 숫자를 바꿔 원문 이어붙이기로 폴백된 턴. */
  verification?: VerificationResult | null;
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
            {meta.stub && <span className="agent-stub-badge">준비 중</span>}
          </div>
        )}
        {turn.verification && !turn.verification.ok && (
          <div
            className="verify-badge"
            title="여러 안내를 합치는 과정에서 숫자가 달라질 수 있어, 각 전문 안내의 원문을 그대로 보여드립니다."
          >
            ⚠️ 확인필요 · 원문 그대로 표시
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
