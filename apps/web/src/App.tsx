import { useEffect, useRef, useState } from "react";
import "./App.css";
import { AgentStrip } from "./components/AgentStrip";
import { ChatMessage, type Turn } from "./components/ChatMessage";
import { FamilySetup } from "./components/FamilySetup";
import { SuggestionChips } from "./components/SuggestionChips";
import { API_BASE_URL, sendChatMessage } from "./lib/api";
import type { AgentName } from "./types";

const FAMILY_GRAPH_ID_KEY = "family_graph_id";
const FAMILY_MEMBER_COUNT_KEY = "family_member_count";
const FAMILY_SETUP_SKIPPED_KEY = "family_setup_skipped";

const WELCOME_TURN: Turn = {
  id: "welcome",
  role: "assistant",
  agent: "heir_navigator",
  text:
    "안녕하세요, 가족 자산 준비 AI 에이전트입니다.\n" +
    "상속 절차 안내, 유언장 요건 점검, 예상 상속세 계산까지 도와드려요.\n\n" +
    "아래에서 궁금한 주제를 선택하거나, 편하게 메시지로 물어보세요.",
};

function createSessionId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function App() {
  const [sessionId, setSessionId] = useState<string>(createSessionId);
  const [turns, setTurns] = useState<Turn[]>([WELCOME_TURN]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [devMode, setDevMode] = useState(false);
  const [activeAgent, setActiveAgent] = useState<AgentName | null>(null);
  const [familyGraphId, setFamilyGraphId] = useState<string | null>(() =>
    localStorage.getItem(FAMILY_GRAPH_ID_KEY),
  );
  const [familyMemberCount, setFamilyMemberCount] = useState<number>(() =>
    Number(localStorage.getItem(FAMILY_MEMBER_COUNT_KEY) ?? "0"),
  );
  // 첫 진입이면 온보딩부터. 이미 입력했거나 "나중에"를 눌렀으면 바로 채팅으로.
  const [view, setView] = useState<"onboarding" | "chat">(() =>
    localStorage.getItem(FAMILY_GRAPH_ID_KEY) ||
    localStorage.getItem(FAMILY_SETUP_SKIPPED_KEY)
      ? "chat"
      : "onboarding",
  );
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, loading]);

  const resetSession = () => {
    setSessionId(createSessionId());
    setTurns([WELCOME_TURN]);
    setActiveAgent(null);
    setInput("");
  };

  const handleSend = async (rawText?: string) => {
    const text = (rawText ?? input).trim();
    if (!text || loading) return;

    const userTurn: Turn = { id: `u-${Date.now()}`, role: "user", text };
    setTurns((prev) => [...prev, userTurn]);
    setInput("");
    setLoading(true);

    const result = await sendChatMessage(sessionId, text, familyGraphId);

    if (result.ok && result.response) {
      const output = result.response;
      setActiveAgent(output.agent);
      setTurns((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          agent: output.agent,
          text: output.reply,
          debug: {
            agent: output.agent,
            nextAction: output.next_action ?? null,
            request: result.request,
            response: output,
            errorMessage: null,
            latencyMs: result.latencyMs,
            status: result.status,
          },
        },
      ]);
    } else {
      setTurns((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          role: "assistant",
          isError: true,
          text:
            "죄송해요, 지금 서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.\n" +
            "(개발자 모드를 켜면 자세한 오류 내용을 확인할 수 있어요.)",
          debug: {
            agent: null,
            nextAction: null,
            request: result.request,
            response: null,
            errorMessage: result.errorMessage,
            latencyMs: result.latencyMs,
            status: result.status,
          },
        },
      ]);
    }

    setLoading(false);
  };

  const handleSetupDone = (id: string, memberCount: number) => {
    localStorage.setItem(FAMILY_GRAPH_ID_KEY, id);
    localStorage.setItem(FAMILY_MEMBER_COUNT_KEY, String(memberCount));
    localStorage.removeItem(FAMILY_SETUP_SKIPPED_KEY);
    setFamilyGraphId(id);
    setFamilyMemberCount(memberCount);
    setView("chat");
  };

  const handleSetupSkip = () => {
    localStorage.setItem(FAMILY_SETUP_SKIPPED_KEY, "1");
    setView("chat");
  };

  if (view === "onboarding") {
    return (
      <div className="app-shell">
        <FamilySetup
          familyGraphId={familyGraphId}
          onDone={handleSetupDone}
          onSkip={handleSetupSkip}
        />
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header-top">
          <div>
            <h1>가족 자산 준비</h1>
            <p className="app-subtitle">누구나 쉽게 준비하는 상속 AI 상담</p>
          </div>
          <div className="app-header-actions">
            <button
              type="button"
              className="icon-btn family-chip"
              onClick={() => setView("onboarding")}
              title="가족 정보 입력/수정"
            >
              👨‍👩‍👧{" "}
              {familyGraphId ? `가족 ${familyMemberCount}명` : "가족 정보 입력"}
            </button>
            <button type="button" className="icon-btn" onClick={resetSession}>
              ↺ 새 상담
            </button>
            <button
              type="button"
              className={`dev-toggle${devMode ? " dev-toggle-on" : ""}`}
              onClick={() => setDevMode((prev) => !prev)}
              aria-pressed={devMode}
            >
              {"</>"} 개발자 모드 {devMode ? "ON" : "OFF"}
            </button>
          </div>
        </div>
        <AgentStrip active={activeAgent} />
      </header>

      <div className="chat-scroll" ref={scrollRef}>
        {turns.map((turn) => (
          <ChatMessage key={turn.id} turn={turn} devMode={devMode} />
        ))}

        {loading && (
          <div className="msg-row msg-row-assistant">
            <div className="msg-assistant-col">
              <div className="bubble bubble-assistant bubble-typing" aria-label="응답 생성 중">
                <span className="dot" />
                <span className="dot" />
                <span className="dot" />
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="composer">
        <SuggestionChips onPick={(msg) => handleSend(msg)} disabled={loading} />
        <div className="composer-row">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                handleSend();
              }
            }}
            placeholder="메시지를 입력하세요"
            disabled={loading}
          />
          <button
            type="button"
            className="send-btn"
            onClick={() => handleSend()}
            disabled={loading || !input.trim()}
          >
            보내기
          </button>
        </div>
        {devMode && (
          <div className="dev-session-info">
            session_id: <code>{sessionId}</code> · API: <code>{API_BASE_URL}</code>
          </div>
        )}
      </div>
    </div>
  );
}
