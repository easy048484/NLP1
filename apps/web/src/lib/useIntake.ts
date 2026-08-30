import { useCallback, useRef, useState } from "react";
import {
  addFamilyMember,
  ensureFamilyGraph,
  getFamilyGraph,
  updateFamilyMember,
} from "./familyGraph";
import {
  buildChildMembers,
  buildParentMember,
  buildSpouseMember,
  childrenCountOptionLabel,
  getNextStep,
  CHILDREN_COUNT_QUESTION,
  CHILDREN_MINOR_QUESTION,
  PARENTS_QUESTION,
  SPOUSE_QUESTION,
  EMPTY_ANSWERS,
  type IntakeAnswers,
  type IntakeStepId,
} from "./familyIntakeFlow";
import {
  getIntakeAnswers,
  getIntakeProgress,
  setIntakeAnswers as persistIntakeAnswers,
  setIntakeProgress,
  clearIntakeAnswers,
  type StoredIntakeAnswers,
} from "./familyGraphStorage";
export type IntakePhase = "optin" | IntakeStepId;

export interface IntakeState {
  phase: IntakePhase;
  answers: IntakeAnswers;
  history: { question: string; answer: string }[];
  busy: boolean;
  error: string | null;
  question: string | null;
  begin: () => void;
  decline: () => void;
  answerSpouse: (v: boolean) => Promise<void>;
  answerChildrenCount: (n: number) => Promise<void>;
  answerChildrenMinor: (n: number) => Promise<void>;
  answerParents: (v: boolean) => Promise<void>;
}

const QUESTION_FOR: Record<IntakeStepId, string> = {
  spouse: SPOUSE_QUESTION,
  children_count: CHILDREN_COUNT_QUESTION,
  children_minor: CHILDREN_MINOR_QUESTION,
  parents: PARENTS_QUESTION,
  complete: "",
};

/**
 * 가족 인테이크 상태 머신 + family_graph REST 저장.
 * FamilyIntake.tsx 의 오케스트레이션 로직을 화면 UI와 분리해 훅으로 옮긴 것.
 */
export function useIntake({
  familyGraphId,
  onFamilyGraphIdChange,
  onGraphRefetched,
  onComplete,
}: {
  familyGraphId: string | null;
  onFamilyGraphIdChange: (id: string) => void;
  onGraphRefetched?: () => void;
  onComplete: () => void;
}): IntakeState {
  const initialProgress = getIntakeProgress();
  const [phase, setPhase] = useState<IntakePhase>(
    initialProgress && initialProgress !== "complete" && initialProgress !== "declined"
      ? initialProgress
      : "optin",
  );
  const [answers, setAnswers] = useState<IntakeAnswers>(getIntakeAnswers() ?? EMPTY_ANSWERS);
  const [history, setHistory] = useState<{ question: string; answer: string }[]>([]);
  const [childMemberIds, setChildMemberIds] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [graphId, setGraphId] = useState<string | null>(familyGraphId);
  //: ensureGraphId 가 이번 세션에 서버 존재를 한 번이라도 확인했는지.
  const graphVerified = useRef(false);

  const persist = (next: IntakeAnswers) => {
    setAnswers(next);
    persistIntakeAnswers(next as StoredIntakeAnswers);
  };

  const advance = (from: IntakeStepId, next: IntakeAnswers) => {
    const step = getNextStep(from, next);
    if (step === "complete") {
      setIntakeProgress("complete");
      clearIntakeAnswers();
      setPhase("complete");
      onComplete();
    } else {
      setIntakeProgress(step);
      setPhase(step);
    }
  };

  const ensureGraphId = useCallback(async (): Promise<string | null> => {
    if (graphId && graphVerified.current) return graphId;
    // 저장된 id 를 서버에서 검증(없으면 새로 생성). 배포 시 DB 재생성 등으로
    // 저장된 id 가 죽었을 때 "family_graph를 찾을 수 없습니다" 404 로 막히던 것 방지.
    const res = await ensureFamilyGraph();
    if (!res.ok || !res.data) {
      setError(res.errorMessage ?? "가족 구성원 정보를 저장하지 못했어요.");
      return null;
    }
    graphVerified.current = true;
    if (res.data.id !== graphId) {
      setGraphId(res.data.id);
      onFamilyGraphIdChange(res.data.id);
    }
    return res.data.id;
  }, [graphId, onFamilyGraphIdChange]);

  const answerSpouse = async (value: boolean) => {
    setBusy(true);
    setError(null);
    const gid = await ensureGraphId();
    if (!gid) return setBusy(false);
    if (value) {
      const res = await addFamilyMember(gid, buildSpouseMember());
      if (!res.ok) {
        setError(res.errorMessage ?? "배우자 정보를 저장하지 못했어요.");
        return setBusy(false);
      }
    }
    setHistory((h) => [...h, { question: SPOUSE_QUESTION, answer: value ? "네" : "아니요" }]);
    const next = { ...answers, spouseAlive: value };
    persist(next);
    onGraphRefetched?.();
    advance("spouse", next);
    setBusy(false);
  };

  const answerChildrenCount = async (count: number) => {
    setBusy(true);
    setError(null);
    const gid = await ensureGraphId();
    if (!gid) return setBusy(false);
    const ids: number[] = [];
    for (const member of buildChildMembers(count)) {
      const res = await addFamilyMember(gid, member);
      if (!res.ok || !res.data) {
        setError(res.errorMessage ?? "자녀 정보를 저장하지 못했어요.");
        return setBusy(false);
      }
      ids.push(res.data.id);
    }
    setChildMemberIds(ids);
    setHistory((h) => [
      ...h,
      { question: CHILDREN_COUNT_QUESTION, answer: childrenCountOptionLabel(count) },
    ]);
    const next = { ...answers, childrenCount: count };
    persist(next);
    onGraphRefetched?.();
    advance("children_count", next);
    setBusy(false);
  };

  const answerChildrenMinor = async (minorCount: number) => {
    setBusy(true);
    setError(null);
    const gid = await ensureGraphId();
    if (!gid) return setBusy(false);
    let ids = childMemberIds;
    if (ids.length === 0) {
      const res = await getFamilyGraph(gid);
      if (!res.ok || !res.data) {
        setError(res.errorMessage ?? "자녀 정보를 불러오지 못했어요.");
        return setBusy(false);
      }
      ids = res.data.members.filter((m) => m.relation === "child").map((m) => m.id);
      setChildMemberIds(ids);
    }
    for (const memberId of ids.slice(0, minorCount)) {
      const res = await updateFamilyMember(gid, memberId, { is_minor: true });
      if (!res.ok) {
        setError(res.errorMessage ?? "미성년 여부를 저장하지 못했어요.");
        return setBusy(false);
      }
    }
    setHistory((h) => [...h, { question: CHILDREN_MINOR_QUESTION, answer: `${minorCount}명` }]);
    const next = { ...answers, minorChildrenCount: minorCount };
    persist(next);
    onGraphRefetched?.();
    advance("children_minor", next);
    setBusy(false);
  };

  const answerParents = async (value: boolean) => {
    setBusy(true);
    setError(null);
    const gid = await ensureGraphId();
    if (!gid) return setBusy(false);
    if (value) {
      const res = await addFamilyMember(gid, buildParentMember());
      if (!res.ok) {
        setError(res.errorMessage ?? "부모님 정보를 저장하지 못했어요.");
        return setBusy(false);
      }
    }
    setHistory((h) => [...h, { question: PARENTS_QUESTION, answer: value ? "네" : "아니요" }]);
    const next = { ...answers, parentsAlive: value };
    persist(next);
    onGraphRefetched?.();
    advance("parents", next);
    setBusy(false);
  };

  const begin = () => setPhase("spouse");
  const decline = () => {
    setIntakeProgress("declined");
    onComplete();
  };

  return {
    phase,
    answers,
    history,
    busy,
    error,
    question: phase === "optin" || phase === "complete" ? null : QUESTION_FOR[phase],
    begin,
    decline,
    answerSpouse,
    answerChildrenCount,
    answerChildrenMinor,
    answerParents,
  };
}
