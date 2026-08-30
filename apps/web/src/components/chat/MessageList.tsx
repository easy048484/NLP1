import { useEffect, useRef, type ReactNode } from "react";
import { useApp, type Turn } from "../../lib/appState";
import { useDevMode } from "../AppShell";
import { AssistantResponse } from "./AssistantResponse";
import { DevPanel } from "./DevPanel";

export function MessageList({ children }: { children?: ReactNode }) {
  const { turns, loading } = useApp();
  const scrollRef = useRef<HTMLDivElement>(null);
  const devMode = useDevMode();

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [turns, loading]);

  return (
    <div className="chat-scroll" ref={scrollRef}>
      <div className="chat-log" role="log" aria-live="polite" aria-label="상담 대화">
        {turns.map((turn) => (
          <MessageRow key={turn.id} turn={turn} devMode={devMode} />
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

function MessageRow({ turn, devMode }: { turn: Turn; devMode: boolean }) {
  if (turn.role === "user") {
    return (
      <div className="msg-row msg-user">
        <div className="user-note">
          <span className="user-note-tag">나</span>
          {turn.text}
        </div>
      </div>
    );
  }

  if (turn.isError) {
    return (
      <div className="msg-row msg-assistant">
        <div className="bubble bubble-assistant bubble-error">{turn.errorText}</div>
        {devMode && turn.debug && <DevPanel debug={turn.debug} />}
      </div>
    );
  }

  return (
    <div className="msg-row msg-assistant">
      {turn.response && <AssistantResponse response={turn.response} />}
      {devMode && turn.debug && <DevPanel debug={turn.debug} />}
    </div>
  );
}
