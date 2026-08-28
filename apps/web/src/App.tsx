import { useEffect, useRef, useState } from "react";
import "./App.css";
import { AgentStrip } from "./components/AgentStrip";
import { AuthScreen } from "./components/AuthScreen";
import { ChatMessage, type Turn } from "./components/ChatMessage";
import { FamilyGraphPanel } from "./components/FamilyGraphPanel";
import { COMPLETE_MESSAGE, EMPTY_ANSWERS, FamilyIntake } from "./components/FamilyIntake";
import { SuggestionChips } from "./components/SuggestionChips";
import { API_BASE_URL, sendChatMessage } from "./lib/api";
import { getStoredAuth, logout, type StoredAuth } from "./lib/auth";
import { claimFamilyGraph, getMyFamilyGraph } from "./lib/familyGraph";
import {
  clearFamilyGraphId,
  clearIntakeAnswers,
  clearIntakeProgress,
  getFamilyGraphId,
  getIntakeAnswers,
  getIntakeProgress,
  setFamilyGraphId as persistFamilyGraphId,
  setIntakeProgress,
  type IntakeProgress,
} from "./lib/familyGraphStorage";
import type { IntakeStepId } from "./lib/familyIntakeFlow";
import type { AgentName } from "./types";

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

/** 인테이크를 아직 보여줘야 하는지: "complete"/"declined"가 아니면 계속 보여줍니다. */
function shouldShowIntake(progress: IntakeProgress | null): boolean {
  return progress !== "complete" && progress !== "declined";
}

export default function App() {
  const [auth, setAuth] = useState<StoredAuth | null>(getStoredAuth);
  const [sessionId, setSessionId] = useState<string>(createSessionId);
  const [turns, setTurns] = useState<Turn[]>([WELCOME_TURN]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [devMode, setDevMode] = useState(false);
  const [activeAgent, setActiveAgent] = useState<AgentName | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // family_graph 인테이크 상태 — localStorage 값으로 마운트 시 한 번만 초기화합니다.
  // (family_graph_입력_플로우_계획_0823.md 4절/6절 참고)
  const [familyGraphId, setFamilyGraphId] = useState<string | null>(() =>
    getFamilyGraphId(),
  );
  const [intakeVisible, setIntakeVisible] = useState<boolean>(() =>
    shouldShowIntake(getIntakeProgress()),
  );
  const [intakePhase] = useState<"optin" | IntakeStepId>(() => {
    const progress = getIntakeProgress();
    if (progress && progress !== "complete" && progress !== "declined") {
      return progress;
    }
    return "optin";
  });
  const [intakeAnswers] = useState(() => getIntakeAnswers() ?? EMPTY_ANSWERS);
  const [showFamilyPanel, setShowFamilyPanel] = useState(false);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, loading, intakeVisible]);

  // 로그인 상태가 되면 이 계정에 연결된 가족관계 그래프를 맞춥니다:
  //  1) 로그인 전 익명으로 만든 그래프가 있으면 계정에 연결(claim)하고
  //  2) 서버에 이미 저장된 내 그래프(구성원 있음)가 있으면 인테이크를 건너뜁니다.
  useEffect(() => {
    if (!auth) return;
    let cancelled = false;

    (async () => {
      const localId = getFamilyGraphId();
      if (localId) {
        await claimFamilyGraph(localId); // 이미 내 것이면 무해, 남의 것이면 무시됨
      }
      const mine = await getMyFamilyGraph();
      if (cancelled) return;
      if (mine.ok && mine.data) {
        persistFamilyGraphId(mine.data.id);
        setFamilyGraphId(mine.data.id);
        if (mine.data.members.length > 0) {
          setIntakeProgress("complete");
          setIntakeVisible(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [auth]);

  const handleAuthed = (next: StoredAuth) => {
    setAuth(next);
  };

  const handleLogout = () => {
    logout();
    clearFamilyGraphId();
    clearIntakeProgress();
    clearIntakeAnswers();
    setAuth(null);
    setFamilyGraphId(null);
    setSessionId(createSessionId());
    setTurns([WELCOME_TURN]);
    setActiveAgent(null);
    setIntakeVisible(true);
  };

  const resetSession = () => {
    // family_graph는 세션보다 오래 사는 데이터라(family_graph/models.py 상단
    // docstring), "새 상담"은 session_id/turns만 초기화하고 family_graph_id는
    // 그대로 유지합니다 — 새 상담에서도 배우자·자녀 질문을 다시 안 받게 됩니다.
    setSessionId(createSessionId());
    setTurns([WELCOME_TURN]);
    setActiveAgent(null);
    setInput("");
  };

  const handleIntakeFinished = (status: "complete" | "declined") => {
    setIntakeVisible(false);
    if (status === "complete") {
      setTurns((prev) => [
        ...prev,
        { id: `intake-done-${Date.now()}`, role: "assistant", text: COMPLETE_MESSAGE },
      ]);
    }
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

  if (!auth) {
    return <AuthScreen onAuthed={handleAuthed} />;
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
            <span className="app-user">{auth.user.name} 님</span>
            <button
              type="button"
              className="icon-btn"
              onClick={() => setShowFamilyPanel(true)}
            >
              👪 가족 구성원
            </button>
            <button type="button" className="icon-btn" onClick={resetSession}>
              ↺ 새 상담
            </button>
            <button type="button" className="icon-btn" onClick={handleLogout}>
              로그아웃
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

        {intakeVisible && (
          <FamilyIntake
            initialPhase={intakePhase}
            familyGraphId={familyGraphId}
            initialAnswers={intakeAnswers}
            onFamilyGraphIdChange={setFamilyGraphId}
            onFinished={handleIntakeFinished}
          />
        )}

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

      {showFamilyPanel && (
        <FamilyGraphPanel
          familyGraphId={familyGraphId}
          onFamilyGraphIdChange={setFamilyGraphId}
          onClose={() => setShowFamilyPanel(false)}
        />
      )}
    </div>
  );
}
