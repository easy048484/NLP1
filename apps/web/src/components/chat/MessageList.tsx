import { useEffect, useRef, type ReactNode, type Ref } from "react";
import { useApp, type Turn } from "../../lib/appState";
import { AssistantResponse } from "./AssistantResponse";

export function MessageList({ children }: { children?: ReactNode }) {
  const { turns, loading } = useApp();
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastRowRef = useRef<HTMLDivElement>(null);

  const lastTurn = turns[turns.length - 1];
  useEffect(() => {
    // 새 답변이 오면 그 답변의 첫머리가 보이도록, 그 외에는 맨 아래로.
    if (lastTurn?.role === "assistant" && lastRowRef.current) {
      lastRowRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      scrollRef.current?.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [turns, loading, lastTurn?.role]);

  return (
    <div className="chat-scroll" ref={scrollRef}>
      <div className="chat-log" role="log" aria-live="polite" aria-label="상담 대화">
        {turns.map((turn, i) => (
          <MessageRow
            key={turn.id}
            turn={turn}
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

function MessageRow({ turn, rowRef }: { turn: Turn; rowRef?: Ref<HTMLDivElement> }) {
  if (turn.role === "user") {
    return (
      <div className="msg-row msg-user" ref={rowRef}>
        <div className="user-note">
          <span className="user-note-tag">나</span>
          {turn.text}
        </div>
      </div>
    );
  }

  if (turn.isError) {
    return (
      <div className="msg-row msg-assistant" ref={rowRef}>
        <div className="bubble bubble-assistant bubble-error">{turn.errorText}</div>
      </div>
    );
  }

  return (
    <div className="msg-row msg-assistant" ref={rowRef}>
      {turn.response ? (
        <AssistantResponse response={turn.response} />
      ) : (
        // 재로그인 후 복원된 지난 대화. 구조화된 응답(에이전트 카드·계획표)은
        // 저장하지 않으므로 텍스트만 있고, 그래서 말풍선으로만 보여준다.
        turn.text && <div className="bubble bubble-assistant">{turn.text}</div>
      )}
    </div>
  );
}
