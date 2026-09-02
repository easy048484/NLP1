import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type {
  AgentInput,
  AgentPlan,
  ChatResponse,
  ConsultAxis,
  EstateSummary,
  FamilyGraphOut,
  WillStatus,
} from "../types";
import { sendChatMessage } from "./api";
import { getStoredAuth, logout as clearStoredAuth, type StoredAuth } from "./auth";
import { getAxis, setAxis as persistAxis, clearAxis } from "./consult";
import {
  clearFamilyGraphId,
  clearIntakeAnswers,
  clearIntakeProgress,
  getFamilyGraphId,
  setFamilyGraphId as persistFamilyGraphId,
} from "./familyGraphStorage";
import {
  SESSION_ID_KEY,
  clearAllScopedKeys,
  promoteScopedKeys,
  readScoped,
  writeScoped,
} from "./scopedStorage";
import { fetchLatestSession } from "./sessions";

/** 대화 한 턴. assistant 턴은 정규화된 합성 응답 전체를 들고 있다. */
export interface Turn {
  id: string;
  role: "user" | "assistant";
  /** user 턴의 텍스트 */
  text?: string;
  /** user 턴에 사진을 첨부했는지 (원본 base64 는 보관하지 않는다) */
  hasImage?: boolean;
  /** assistant 턴의 합성 응답 */
  response?: ChatResponse;
  isError?: boolean;
  errorText?: string;
  /** 개발자 모드용 */
  debug?: {
    request: AgentInput;
    raw: unknown;
    status: number | null;
    latencyMs: number;
    errorMessage: string | null;
  };
}

function createSessionId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * 새 session_id를 만들어 저장까지 합니다.
 *
 * 예전에는 session_id를 어디에도 저장하지 않아서(useState(createSessionId)),
 * 새로고침 한 번에 서버 세션과의 연결이 끊기고 대화가 처음부터 시작됐습니다.
 * 로그인해도 마찬가지였습니다 — 서버가 30일 보관해도 클라이언트가 그 세션의
 * 이름을 잊어버리니 이어갈 방법이 없었습니다.
 *
 * 저장 위치는 로그인 여부에 따라 갈립니다(scopedStorage): 비로그인이면 탭을
 * 닫을 때 사라지고, 로그인이면 다음 방문까지 남습니다.
 */
function startNewSession(): string {
  const id = createSessionId();
  writeScoped(SESSION_ID_KEY, id);
  return id;
}

/** 저장된 session_id가 있으면 이어쓰고, 없으면 새로 시작합니다. */
function resumeOrStartSession(): string {
  return readScoped(SESSION_ID_KEY) ?? startNewSession();
}

interface AppStateValue {
  auth: StoredAuth | null;
  setAuth: (a: StoredAuth) => void;
  logout: () => void;

  sessionId: string;
  resetChat: () => void;
  /** 재로그인 직후 서버에 남아 있던 지난 대화를 이어붙인다. */
  restoreLastSession: () => Promise<boolean>;

  familyGraphId: string | null;
  setFamilyGraphId: (id: string | null) => void;

  axis: ConsultAxis | null;
  setAxis: (a: ConsultAxis) => void;

  turns: Turn[];
  loading: boolean;
  send: (
    text: string,
    opts?: {
      context?: Record<string, unknown>;
      image?: { base64: string; mediaType: string };
    },
  ) => Promise<void>;

  /** 최근 응답에서 뽑은 컨텍스트 패널용 상태 */
  plan: AgentPlan | null;
  estate: EstateSummary | null;
  willStatus: WillStatus | null;
  familyGraph: FamilyGraphOut | null;
  setFamilyGraph: (g: FamilyGraphOut | null) => void;

  /** 타임라인 체크박스 로컬 상태 */
  planChecks: Record<string, boolean>;
  togglePlanCheck: (id: string) => void;
}

const Ctx = createContext<AppStateValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [auth, setAuthState] = useState<StoredAuth | null>(getStoredAuth);
  const [sessionId, setSessionId] = useState(resumeOrStartSession);
  const [familyGraphId, setFamilyGraphIdState] = useState<string | null>(getFamilyGraphId);
  const [axis, setAxisState] = useState<ConsultAxis | null>(getAxis);

  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);

  const [plan, setPlan] = useState<AgentPlan | null>(null);
  const [estate, setEstate] = useState<EstateSummary | null>(null);
  const [willStatus, setWillStatus] = useState<WillStatus | null>(null);
  const [familyGraph, setFamilyGraph] = useState<FamilyGraphOut | null>(null);
  const [planChecks, setPlanChecks] = useState<Record<string, boolean>>({});

  const axisRef = useRef(axis);
  axisRef.current = axis;
  const fgRef = useRef(familyGraphId);
  fgRef.current = familyGraphId;

  /**
   * 서버에 남아 있는 내 마지막 대화를 이어받는다.
   *
   * 로그아웃하면 session_id 를 버리므로, 다시 로그인했을 때 이걸 호출하지
   * 않으면 서버가 30일 보관한 대화를 영영 못 찾습니다. 지난 대화는 텍스트로만
   * 복원됩니다 — 에이전트 카드·계획표 같은 구조화된 응답은 저장하지 않으므로,
   * 다시 실행한 결과가 아니라 지나간 기록으로 보여줍니다.
   *
   * 이어볼 대화가 없거나 조회에 실패하면 false. 그 경우 지금 세션 그대로
   * 새 대화를 시작하면 됩니다 — 이어보기 실패가 로그인을 막을 이유는 없습니다.
   */
  const restoreLastSession = useCallback(async () => {
    const latest = await fetchLatestSession();
    if (!latest) return false;

    setSessionId(latest.session_id);
    writeScoped(SESSION_ID_KEY, latest.session_id);
    if (latest.family_graph_id) setFamilyGraphIdState(latest.family_graph_id);

    setTurns(
      latest.history.map((turn, i) => ({
        id: `restored-${i}`,
        role: turn.role,
        text: turn.content,
      })),
    );
    return true;
  }, []);

  const setAuth = useCallback((a: StoredAuth) => {
    // 비로그인으로 쓰던 값(session_id, family_graph_id, 인테이크 진행 상태)을
    // 계정 저장소로 옮깁니다. 하던 상담을 그대로 이어가면서, 다음 방문에도
    // 남게 하려면 이 승격이 필요합니다. 서버 쪽 세션은 다음 요청에서
    // 자동으로 계정에 붙습니다(orchestrator/router.node_load_session).
    promoteScopedKeys();
    setAuthState(a);
  }, []);

  const logout = useCallback(() => {
    // clearStoredAuth 를 먼저 — 그래야 이후 저장이 비로그인 저장소로 갑니다.
    clearStoredAuth();
    clearFamilyGraphId();
    clearIntakeProgress();
    clearIntakeAnswers();
    clearAxis();
    // 위 개별 정리가 놓친 키까지 양쪽 저장소에서 한 번 더 훑어 지웁니다.
    clearAllScopedKeys();
    setAuthState(null);
    setFamilyGraphIdState(null);
    setAxisState(null);
    setTurns([]);
    setPlan(null);
    setEstate(null);
    setWillStatus(null);
    setFamilyGraph(null);
    setPlanChecks({});
    setSessionId(startNewSession());
  }, []);

  const resetChat = useCallback(() => {
    setSessionId(startNewSession());
    setTurns([]);
    setPlan(null);
    setEstate(null);
    setWillStatus(null);
    setPlanChecks({});
  }, []);
  // 새 상담을 시작하면 이전 상담에서 뽑아둔 재산·유언장·절차 요약도 비운다.

  const setFamilyGraphId = useCallback((id: string | null) => {
    setFamilyGraphIdState(id);
    if (id) persistFamilyGraphId(id);
    else clearFamilyGraphId();
  }, []);

  const setAxis = useCallback((a: ConsultAxis) => {
    setAxisState(a);
    persistAxis(a);
  }, []);

  const togglePlanCheck = useCallback((id: string) => {
    setPlanChecks((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  const send = useCallback(
    async (
      rawText: string,
      opts?: {
        context?: Record<string, unknown>;
        image?: { base64: string; mediaType: string };
      },
    ) => {
      const text = rawText.trim();
      if ((!text && !opts?.image) || loading) return;
      const message = text || "사진을 올렸어요";

      setTurns((prev) => [
        ...prev,
        {
          id: `u-${Date.now()}`,
          role: "user",
          text: message,
          hasImage: !!opts?.image,
        },
      ]);
      setLoading(true);

      const result = await sendChatMessage(sessionId, message, {
        context: opts?.context,
        image: opts?.image,
        familyGraphId: fgRef.current,
        axis: axisRef.current,
      });

      if (result.ok && result.response) {
        const res = result.response;
        setTurns((prev) => [
          ...prev,
          {
            id: `a-${Date.now()}`,
            role: "assistant",
            response: res,
            debug: {
              request: result.request,
              raw: result.raw,
              status: result.status,
              latencyMs: result.latencyMs,
              errorMessage: result.errorMessage,
            },
          },
        ]);
        if (res.plan) setPlan(res.plan);
        if (res.estate) setEstate(res.estate);
        if (res.will_status?.checked) setWillStatus(res.will_status);
        if (res.family_graph) setFamilyGraph(res.family_graph);
      } else {
        setTurns((prev) => [
          ...prev,
          {
            id: `err-${Date.now()}`,
            role: "assistant",
            isError: true,
            errorText:
              "지금 서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.\n" +
              "(개발자 모드를 켜면 자세한 오류를 볼 수 있어요.)",
            debug: {
              request: result.request,
              raw: result.raw,
              status: result.status,
              latencyMs: result.latencyMs,
              errorMessage: result.errorMessage,
            },
          },
        ]);
      }
      setLoading(false);
    },
    [loading, sessionId],
  );

  const value = useMemo<AppStateValue>(
    () => ({
      auth,
      setAuth,
      logout,
      sessionId,
      resetChat,
      restoreLastSession,
      familyGraphId,
      setFamilyGraphId,
      axis,
      setAxis,
      turns,
      loading,
      send,
      plan,
      estate,
      willStatus,
      familyGraph,
      setFamilyGraph,
      planChecks,
      togglePlanCheck,
    }),
    [
      auth,
      setAuth,
      logout,
      sessionId,
      resetChat,
      restoreLastSession,
      familyGraphId,
      setFamilyGraphId,
      axis,
      setAxis,
      turns,
      loading,
      send,
      plan,
      estate,
      willStatus,
      familyGraph,
      planChecks,
      togglePlanCheck,
    ],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useApp(): AppStateValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp must be used within AppProvider");
  return v;
}
