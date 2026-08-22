import { useState } from "react";
import type { AgentInput, AgentName, AgentOutput } from "../types";
import { JsonBlock } from "./JsonBlock";

export interface TurnDebugInfo {
  agent: AgentName | null;
  nextAction: string | null;
  request: AgentInput;
  response: AgentOutput | null;
  errorMessage: string | null;
  latencyMs: number;
  status: number | null;
}

/**
 * "개발자용" 화면 요구사항 — 이번 턴에 실제로 호출된 에이전트와, 오케스트레이터에
 * 보낸 요청(AgentInput) / 받은 응답(AgentOutput) 원본 JSON을 그대로 펼쳐볼 수
 * 있게 합니다. 기본은 접힌 상태로, 메시지마다 개별적으로 펼쳐볼 수 있습니다.
 */
export function DevPanel({ debug }: { debug: TurnDebugInfo }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="dev-panel">
      <button
        type="button"
        className="dev-panel-toggle"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
      >
        <span>{"</>"} 개발자 정보</span>
        <span className="dev-panel-meta">
          {debug.agent ?? "호출 실패"} · {debug.latencyMs}ms {open ? "▲" : "▼"}
        </span>
      </button>

      {open && (
        <div className="dev-panel-body">
          <div className="dev-panel-row">
            <span className="dev-panel-key">호출된 에이전트</span>
            <span className="dev-panel-value">{debug.agent ?? "(응답 없음)"}</span>
          </div>
          <div className="dev-panel-row">
            <span className="dev-panel-key">next_action</span>
            <span className="dev-panel-value">
              {debug.nextAction ?? "null"}
            </span>
          </div>
          <div className="dev-panel-row">
            <span className="dev-panel-key">HTTP 상태</span>
            <span className="dev-panel-value">
              {debug.status ?? "네트워크 오류"} · {debug.latencyMs}ms
            </span>
          </div>
          {debug.errorMessage && (
            <div className="dev-panel-row">
              <span className="dev-panel-key">오류</span>
              <span className="dev-panel-value dev-panel-error">
                {debug.errorMessage}
              </span>
            </div>
          )}

          <JsonBlock label="요청 JSON — POST /chat (AgentInput)" value={debug.request} />
          {debug.response && (
            <JsonBlock label="응답 JSON (AgentOutput)" value={debug.response} />
          )}
        </div>
      )}
    </div>
  );
}
