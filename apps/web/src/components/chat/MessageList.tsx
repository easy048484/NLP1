import { useEffect, useRef, type ReactNode } from "react";
import { useApp, type Turn } from "../../lib/appState";
import { useDevMode } from "../AppShell";
import { AssistantResponse } from "./AssistantResponse";
import { DevPanel } from "./DevPanel";

export function MessageList({ children }: { children?: ReactNode }) {
  const { turns, loading } = useApp();
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastRowRef = useRef<HTMLDivElement>(null);
  const devMode = useDevMode();

  const lastTurn = turns[turns.length - 1];
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    // 사용자가 방금 보냈으면 맨 아래로(내 말풍선 보이게), 에이전트 답변이
    // 도착했으면 그 답변의 '윗부분'이 화면 상단에 오도록 — 긴 답변에서
    // 끝만 보이는 걸 막는다.
    if (lastTurn?.role === "assistant" && lastRowRef.current) {
      lastRowRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      scroller.scrollTo({ top: scroller.scrollHeight, behavior: "smooth" });
    }
  }, [turns.length, loading, lastTurn?.role]);

  return (
    <div className="chat-scroll" ref={scrollRef}>
      <div className="chat-log" role="log" aria-live="polite" aria-label="상담 대화">
        {turns.map((turn, i) => (
          <MessageRow
            key={turn.id}
            turn={turn}
            devMode={devMode}
            rowRef={i === turns.length - 1 ? lastRowRef : undefined}
          />
        ))}

        {children}

        {loading && (
          <div className="msg-row msg-assistant">
            <div className="agent-thinking" aria-label="에이전트가 확인하고 있어요">
              <span className="agent-avatar agent-avatar-sm agent-avatar-pulse" aria-hidden="true">
                ✦
              </span>
              <span className="bubble-typing">
                <span className="dot" />
                <span className="dot" />
                <span className="dot" />
              </span>
              <span className="agent-thinking-text">에이전트가 확인하고 있어요</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function MessageRow({
  turn,
  devMode,
  rowRef,
}: {
  turn: Turn;
  devMode: boolean;
  rowRef?: React.Ref<HTMLDivElement>;
}) {
  if (turn.role === "user") {
    return (
      <div className="msg-row msg-user" ref={rowRef}>
        <div className="user-note">
          <span className="user-note-tag">나</span>
          {turn.text}
          {turn.hasImage && <span className="user-note-img">🖼️ 사진</span>}
        </div>
      </div>
    );
  }

  if (turn.isError) {
    return (
      <div className="msg-row msg-assistant" ref={rowRef}>
        <div className="bubble bubble-assistant bubble-error">{turn.errorText}</div>
        {devMode && turn.debug && <DevPanel debug={turn.debug} />}
      </div>
    );
  }

  return (
    <div className="msg-row msg-assistant" ref={rowRef}>
      {turn.response && <AssistantResponse response={turn.response} />}
      {devMode && turn.debug && <DevPanel debug={turn.debug} />}
    </div>
  );
}
