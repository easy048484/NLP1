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

interface AppStateValue {
  auth: StoredAuth | null;
  setAuth: (a: StoredAuth) => void;
  logout: () => void;

  sessionId: string;
  resetChat: () => void;

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
  const [sessionId, setSessionId] = useState(createSessionId);
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

  const setAuth = useCallback((a: StoredAuth) => setAuthState(a), []);

  const logout = useCallback(() => {
    clearStoredAuth();
    clearFamilyGraphId();
    clearIntakeProgress();
    clearIntakeAnswers();
    clearAxis();
    setAuthState(null);
    setFamilyGraphIdState(null);
    setAxisState(null);
    setTurns([]);
    setPlan(null);
    setEstate(null);
    setWillStatus(null);
    setFamilyGraph(null);
    setPlanChecks({});
    setSessionId(createSessionId());
  }, []);

  const resetChat = useCallback(() => {
    setSessionId(createSessionId());
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
