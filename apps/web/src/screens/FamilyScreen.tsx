import { useNavigate } from "react-router-dom";
import { useApp } from "../lib/appState";
import { getFamilyGraph } from "../lib/familyGraph";
import { useIntake } from "../lib/useIntake";
import {
  CHILDREN_COUNT_OPTIONS,
  childrenCountOptionLabel,
  resumeIntroLine,
} from "../lib/familyIntakeFlow";
import { FamilyTree } from "../components/FamilyTree";
import { Button, ChoiceGroup, Eyebrow, GoldRule, YesNo } from "../components/ui";

/**
 * 가족관계 인테이크 — 시각적 가족트리 + 한 번에 한 질문.
 * 민법 1000조 순서(배우자 → 자녀 → 부모), 30초 해피패스, "나중에" 스킵.
 */
export function FamilyScreen() {
  const navigate = useNavigate();
  const { familyGraphId, setFamilyGraphId, familyGraph, setFamilyGraph, axis } = useApp();

  const done = () => navigate(axis === "pre_need" ? "/home" : "/chat");

  const refetch = async () => {
    if (!familyGraphId) return;
    const res = await getFamilyGraph(familyGraphId);
    if (res.ok && res.data) setFamilyGraph(res.data);
  };

  const intake = useIntake({
    familyGraphId,
    onFamilyGraphIdChange: (id) => setFamilyGraphId(id),
    onGraphRefetched: () => void refetch(),
    onComplete: done,
  });

  const members = familyGraph?.members ?? [];
  const centerLabel =
    axis === "pre_need" ? "나" : axis === "post_death" ? "고인" : "기준이 되는 분";
  const heading =
    axis === "pre_need"
      ? "나를 기준으로 가족을 알려주세요"
      : axis === "post_death"
        ? "고인을 기준으로 가족을 알려주세요"
        : "가족을 알려주세요";
  const resume =
    intake.history.length === 0 && intake.phase !== "optin" && intake.phase !== "spouse"
      ? resumeIntroLine(intake.phase, intake.answers)
      : null;

  return (
    <div className="onboarding-screen family-screen">
      <div className="onboarding-inner">
        <Eyebrow>가족관계</Eyebrow>
        <GoldRule />
        <h1>{heading}</h1>
        <p className="onboarding-lede">
          가족관계증명서를 보며 옮겨 적으셔도 됩니다. 실명은 쓰지 않아도 돼요. 한 번
          적어 두면 이후 상속세·절차 상담에서 같은 질문을 반복하지 않습니다.
        </p>

        <div className="family-consent">
          절차 안내를 위해 가족관계 정보를 받아요. 원문은 저장하지 않고, 주민번호 같은
          민감정보는 자동으로 지웁니다.
        </div>

        <FamilyTree members={members} centerLabel={centerLabel} />

        <div className="intake-panel">
          {intake.error && (
            <p className="auth-error" role="alert">
              ⚠ {intake.error} 다시 시도해 주세요.
            </p>
          )}

          {resume && <p className="intake-resume">{resume}</p>}

          {intake.phase === "optin" && (
            <>
              <p className="intake-question">가족 구성원을 지금 알려주시겠어요?</p>
              <div className="intake-actions">
                <Button onClick={intake.begin}>지금 알려드릴게요</Button>
                <Button variant="ghost" onClick={intake.decline}>
                  나중에 할게요
                </Button>
              </div>
            </>
          )}

          {intake.phase === "spouse" && (
            <>
              <p className="intake-question">{intake.question}</p>
              <YesNo onSelect={intake.answerSpouse} disabled={intake.busy} />
            </>
          )}

          {intake.phase === "children_count" && (
            <>
              <p className="intake-question">{intake.question}</p>
              <ChoiceGroup<number>
                options={CHILDREN_COUNT_OPTIONS.map((n) => ({
                  label: childrenCountOptionLabel(n),
                  value: n,
                }))}
                onSelect={intake.answerChildrenCount}
                disabled={intake.busy}
              />
            </>
          )}

          {intake.phase === "children_minor" && (
            <>
              <p className="intake-question">{intake.question}</p>
              <ChoiceGroup<number>
                options={Array.from(
                  { length: (intake.answers.childrenCount ?? 0) + 1 },
                  (_, i) => ({ label: `${i}명`, value: i }),
                )}
                onSelect={intake.answerChildrenMinor}
                disabled={intake.busy}
              />
            </>
          )}

          {intake.phase === "parents" && (
            <>
              <p className="intake-question">{intake.question}</p>
              <YesNo onSelect={intake.answerParents} disabled={intake.busy} />
            </>
          )}

          {intake.history.length > 0 && (
            <ul className="intake-history">
              {intake.history.map((h, i) => (
                <li key={i}>
                  <span>{h.question}</span>
                  <strong>{h.answer}</strong>
                </li>
              ))}
            </ul>
          )}
        </div>

        <button type="button" className="onboarding-skip" onClick={done}>
          건너뛰고 상담 시작
        </button>
      </div>
    </div>
  );
}
