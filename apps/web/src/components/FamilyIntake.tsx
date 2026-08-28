import { useState } from "react";
import {
  addFamilyMember,
  createFamilyGraph,
  getFamilyGraph,
  updateFamilyMember,
} from "../lib/familyGraph";
import {
  CHILDREN_COUNT_OPTIONS,
  CHILDREN_MINOR_QUESTION,
  COMPLETE_MESSAGE,
  EMPTY_ANSWERS,
  PARENTS_QUESTION,
  SPOUSE_QUESTION,
  CHILDREN_COUNT_QUESTION,
  buildChildMembers,
  buildParentMember,
  buildSpouseMember,
  childrenCountOptionLabel,
  getNextStep,
  resumeIntroLine,
  type IntakeAnswers,
  type IntakeStepId,
} from "../lib/familyIntakeFlow";
import {
  setFamilyGraphId as persistFamilyGraphId,
  setIntakeAnswers as persistIntakeAnswers,
  setIntakeProgress,
  clearIntakeAnswers,
  type StoredIntakeAnswers,
} from "../lib/familyGraphStorage";
import { CountStepper } from "./CountStepper";
import { YesNoToggle } from "./YesNoToggle";

interface HistoryEntry {
  question: string;
  answerLabel: string;
}

/**
 * 가족 구성원 인테이크 위젯. `/chat`을 거치지 않는 순수 프론트 상태
 * 머신이고(family_graph_입력_플로우_계획_0823.md 2절 "대안 A"), 답이
 * 채워질 때마다 family_graph REST API로 즉시 저장합니다.
 *
 * initialPhase가 "optin"이면 처음 보여주는 옵트인 카드부터 시작하고,
 * 질문 단계 id면 그 질문부터 이어서 시작합니다(App.tsx가 localStorage
 * 진행 상태를 보고 결정).
 */
export function FamilyIntake({
  initialPhase,
  familyGraphId,
  initialAnswers,
  onFamilyGraphIdChange,
  onFinished,
}: {
  initialPhase: "optin" | IntakeStepId;
  familyGraphId: string | null;
  initialAnswers: IntakeAnswers;
  onFamilyGraphIdChange: (id: string) => void;
  onFinished: (status: "complete" | "declined") => void;
}) {
  const [phase, setPhase] = useState<"optin" | IntakeStepId>(initialPhase);
  const [answers, setAnswers] = useState<IntakeAnswers>(initialAnswers);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [childMemberIds, setChildMemberIds] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [graphId, setGraphId] = useState<string | null>(familyGraphId);

  const persistAnswers = (next: IntakeAnswers) => {
    setAnswers(next);
    persistIntakeAnswers(next as StoredIntakeAnswers);
  };

  const advanceOrFinish = (from: IntakeStepId, next: IntakeAnswers) => {
    const nextStep = getNextStep(from, next);
    if (nextStep === "complete") {
      setIntakeProgress("complete");
      clearIntakeAnswers();
      setPhase("complete");
      onFinished("complete");
    } else {
      setIntakeProgress(nextStep);
      setPhase(nextStep);
    }
  };

  const ensureGraphId = async (): Promise<string | null> => {
    if (graphId) return graphId;
    const res = await createFamilyGraph();
    if (!res.ok || !res.data) {
      setError(res.errorMessage ?? "가족 구성원 정보를 저장하지 못했어요.");
      return null;
    }
    persistFamilyGraphId(res.data.id);
    setGraphId(res.data.id);
    onFamilyGraphIdChange(res.data.id);
    return res.data.id;
  };

  const handleSpouseAnswer = async (value: boolean) => {
    setBusy(true);
    setError(null);

    const gid = await ensureGraphId();
    if (!gid) {
      setBusy(false);
      return;
    }

    if (value) {
      const res = await addFamilyMember(gid, buildSpouseMember());
      if (!res.ok) {
        setError(res.errorMessage ?? "배우자 정보를 저장하지 못했어요.");
        setBusy(false);
        return;
      }
    }

    setHistory((prev) => [
      ...prev,
      { question: SPOUSE_QUESTION, answerLabel: value ? "네" : "아니요" },
    ]);
    const next = { ...answers, spouseAlive: value };
    persistAnswers(next);
    advanceOrFinish("spouse", next);
    setBusy(false);
  };

  const handleChildrenCountAnswer = async (count: number) => {
    if (!graphId) return; // spouse 단계에서 이미 생성됨 — 방어적 처리
    setBusy(true);
    setError(null);

    const ids: number[] = [];
    for (const member of buildChildMembers(count)) {
      const res = await addFamilyMember(graphId, member);
      if (!res.ok || !res.data) {
        setError(res.errorMessage ?? "자녀 정보를 저장하지 못했어요.");
        setBusy(false);
        return;
      }
      ids.push(res.data.id);
    }
    setChildMemberIds(ids);

    setHistory((prev) => [
      ...prev,
      {
        question: CHILDREN_COUNT_QUESTION,
        answerLabel: childrenCountOptionLabel(count),
      },
    ]);
    const next = { ...answers, childrenCount: count };
    persistAnswers(next);
    advanceOrFinish("children_count", next);
    setBusy(false);
  };

  const handleChildrenMinorAnswer = async (minorCount: number) => {
    if (!graphId) return;
    setBusy(true);
    setError(null);

    let ids = childMemberIds;
    if (ids.length === 0) {
      // 새로고침 등으로 이 세션에서 방금 추가한 자녀 id를 모를 때만 다시 조회합니다.
      const res = await getFamilyGraph(graphId);
      if (!res.ok || !res.data) {
        setError(res.errorMessage ?? "자녀 정보를 불러오지 못했어요.");
        setBusy(false);
        return;
      }
      ids = res.data.members.filter((m) => m.relation === "child").map((m) => m.id);
      setChildMemberIds(ids);
    }

    for (const memberId of ids.slice(0, minorCount)) {
      const res = await updateFamilyMember(graphId, memberId, { is_minor: true });
      if (!res.ok) {
        setError(res.errorMessage ?? "미성년 여부를 저장하지 못했어요.");
        setBusy(false);
        return;
      }
    }

    setHistory((prev) => [
      ...prev,
      { question: CHILDREN_MINOR_QUESTION, answerLabel: `${minorCount}명` },
    ]);
    const next = { ...answers, minorChildrenCount: minorCount };
    persistAnswers(next);
    advanceOrFinish("children_minor", next);
    setBusy(false);
  };

  const handleParentsAnswer = async (value: boolean) => {
    if (!graphId) return;
    setBusy(true);
    setError(null);

    if (value) {
      const res = await addFamilyMember(graphId, buildParentMember());
      if (!res.ok) {
        setError(res.errorMessage ?? "부모님 정보를 저장하지 못했어요.");
        setBusy(false);
        return;
      }
    }

    setHistory((prev) => [
      ...prev,
      { question: PARENTS_QUESTION, answerLabel: value ? "네" : "아니요" },
    ]);
    const next = { ...answers, parentsAlive: value };
    persistAnswers(next);
    advanceOrFinish("parents", next);
    setBusy(false);
  };

  const handleOptinDecline = () => {
    setIntakeProgress("declined");
    onFinished("declined");
  };

  if (phase === "complete") {
    return null;
  }

  if (phase === "optin") {
    return (
      <div className="msg-row msg-row-assistant">
        <div className="msg-assistant-col">
          <div className="bubble bubble-assistant intake-card">
            가족 구성원을 먼저 알려주시면, 이후 상속세·상속 절차 상담에서 배우자·자녀
            관련 질문을 줄여드릴 수 있어요. 지금 알려주시겠어요?
          </div>
          <YesNoToggle
            yesLabel="지금 알려드릴게요"
            noLabel="다음에 할게요"
            onSelect={(v) => (v ? setPhase("spouse") : handleOptinDecline())}
          />
        </div>
      </div>
    );
  }

  const resumeNote = history.length === 0 ? resumeIntroLine(phase, answers) : null;

  return (
    <div className="msg-row msg-row-assistant">
      <div className="msg-assistant-col">
        {history.map((entry, i) => (
          <div key={i} className="intake-history-pair">
            <div className="bubble bubble-assistant intake-card">{entry.question}</div>
            <div className="msg-row msg-row-user intake-history-answer">
              <div className="bubble bubble-user">{entry.answerLabel}</div>
            </div>
          </div>
        ))}

        {resumeNote && <div className="intake-resume-note">{resumeNote}</div>}

        {phase === "spouse" && (
          <>
            <div className="bubble bubble-assistant intake-card">{SPOUSE_QUESTION}</div>
            <YesNoToggle onSelect={handleSpouseAnswer} disabled={busy} />
          </>
        )}

        {phase === "children_count" && (
          <>
            <div className="bubble bubble-assistant intake-card">
              {CHILDREN_COUNT_QUESTION}
            </div>
            <CountStepper
              options={[...CHILDREN_COUNT_OPTIONS]}
              formatLabel={childrenCountOptionLabel}
              onSelect={handleChildrenCountAnswer}
              disabled={busy}
            />
          </>
        )}

        {phase === "children_minor" && (
          <>
            <div className="bubble bubble-assistant intake-card">
              {CHILDREN_MINOR_QUESTION}
            </div>
            <CountStepper
              options={Array.from({ length: (answers.childrenCount ?? 0) + 1 }, (_, i) => i)}
              onSelect={handleChildrenMinorAnswer}
              disabled={busy}
            />
          </>
        )}

        {phase === "parents" && (
          <>
            <div className="bubble bubble-assistant intake-card">{PARENTS_QUESTION}</div>
            <YesNoToggle onSelect={handleParentsAnswer} disabled={busy} />
          </>
        )}

        {error && <div className="intake-error">{error} 다시 시도해주세요.</div>}
      </div>
    </div>
  );
}

/** App.tsx가 인테이크 완료 직후 확인 문구를 보여줄 때 재사용합니다. */
export { COMPLETE_MESSAGE, EMPTY_ANSWERS };
