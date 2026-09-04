import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "../lib/appState";
import {
  addFamilyMember,
  deleteFamilyMember,
  ensureFamilyGraph,
  getFamilyGraph,
} from "../lib/familyGraph";
import { FamilyTree } from "../components/FamilyTree";
import { Button, Eyebrow, GoldRule } from "../components/ui";
import type { RelationType } from "../types";

/**
 * 가족관계 인테이크 — "누구 기준인지"를 화면 맨 위에 못박고(고인/나 이름),
 * 배우자 → 자녀 → 부모 순서로 이름과 함께 한 명씩 추가한다.
 *
 * 이전 버전은 배우자 Y/N · 자녀 몇 명 식의 카운트 퀴즈여서 (1) 누구 기준인지
 * 헷갈리고 (2) 추상적인 "자녀 1, 자녀 2"만 남았다. 이름을 받으면 이후 상담에서
 * "첫째분", "배우자분" 처럼 구체적으로 부를 수 있고, 사용자도 자기 가족을
 * 그리는 감각이 생긴다.
 */
type Phase = "spouse" | "children" | "parents";

const ORDINAL = ["첫째", "둘째", "셋째", "넷째", "다섯째", "여섯째"];

export function FamilyScreen() {
  const navigate = useNavigate();
  const { familyGraphId, setFamilyGraphId, familyGraph, setFamilyGraph, axis } =
    useApp();

  const isPreNeed = axis === "pre_need";
  const done = () => navigate(isPreNeed ? "/home" : "/chat");

  const [centerName, setCenterName] = useState("");
  const [phase, setPhase] = useState<Phase>("spouse");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [personName, setPersonName] = useState(""); // 배우자·부모 이름 입력
  const [childName, setChildName] = useState("");
  const [childMinor, setChildMinor] = useState(false);

  const members = familyGraph?.members ?? [];
  const spouse = members.find((m) => m.relation === "spouse");
  const children = members.filter((m) => m.relation === "child");
  const parents = members.filter((m) => m.relation === "parent");

  const centerLabel = centerName.trim() || (isPreNeed ? "나" : "고인");
  const centerNoun = isPreNeed ? "나" : "고인";

  function defaultName(rel: RelationType): string {
    if (rel === "spouse") return "배우자";
    if (rel === "parent") return `${centerNoun}의 부모님`;
    return `${ORDINAL[children.length] ?? `${children.length + 1}번째`} 자녀`;
  }

  async function ensureGraph(): Promise<string | null> {
    if (familyGraphId) return familyGraphId;
    const res = await ensureFamilyGraph();
    if (!res.ok || !res.data) {
      setError(res.errorMessage ?? "가족관계 정보를 저장하지 못했어요.");
      return null;
    }
    setFamilyGraphId(res.data.id);
    setFamilyGraph(res.data);
    return res.data.id;
  }

  async function refetch(id: string) {
    const res = await getFamilyGraph(id);
    if (res.ok && res.data) setFamilyGraph(res.data);
  }

  async function add(
    relation: RelationType,
    name: string,
    is_minor = false,
  ): Promise<boolean> {
    setBusy(true);
    setError(null);
    const id = await ensureGraph();
    if (!id) {
      setBusy(false);
      return false;
    }
    const res = await addFamilyMember(id, {
      name: name.trim() || defaultName(relation),
      relation,
      is_alive: true,
      is_minor,
    });
    if (!res.ok) {
      setError(res.errorMessage ?? "저장에 실패했어요. 다시 시도해 주세요.");
      setBusy(false);
      return false;
    }
    await refetch(id);
    setBusy(false);
    return true;
  }

  async function removeMember(memberId: number) {
    if (!familyGraphId) return;
    setBusy(true);
    await deleteFamilyMember(familyGraphId, memberId);
    await refetch(familyGraphId);
    setBusy(false);
  }

  const heading = isPreNeed
    ? "내 가족을 알려주세요"
    : "고인의 가족을 알려주세요";

  return (
    <div className="onboarding-screen family-screen">
      <div className="onboarding-inner">
        <Eyebrow>가족관계</Eyebrow>
        <GoldRule />
        <h1>{heading}</h1>
        <p className="onboarding-lede">
          아래에 적는 가족은 모두 <strong>{centerNoun} 기준</strong>입니다 —
          {centerNoun}의 배우자·자녀·부모. 실명 대신 "첫째"처럼 적어도 됩니다.
        </p>

        {/* ── 기준 인물 앵커 ── */}
        <div className="family-anchor">
          <label className="family-anchor-label" htmlFor="centerName">
            {isPreNeed ? "기준: 나" : "누구의 상속인가요?"}
          </label>
          <input
            id="centerName"
            className="family-anchor-input"
            value={centerName}
            onChange={(e) => setCenterName(e.target.value)}
            placeholder={
              isPreNeed ? "내 이름 (선택)" : "고인 성함 (선택, 예: 김O수)"
            }
          />
          <p className="family-anchor-hint">
            {isPreNeed
              ? "내가 세상을 떠났을 때를 기준으로 준비합니다."
              : "이분이 상속의 기준입니다. 아래 가족은 이분의 배우자·자녀·부모."}
          </p>
        </div>

        <div className="family-consent">
          절차 안내를 위해 가족관계 정보를 받아요. 원문은 저장하지 않고, 주민번호
          같은 민감정보는 자동으로 지웁니다.
        </div>

        <FamilyTree members={members} centerLabel={centerLabel} />

        {error && (
          <p className="auth-error" role="alert">
            ⚠ {error}
          </p>
        )}

        <div className="intake-panel">
          {/* 1) 배우자 */}
          {phase === "spouse" && (
            <>
              <p className="intake-question">
                {centerNoun === "나" ? "배우자가 있으세요?" : `${centerNoun}의 배우자가 생존해 계신가요?`}
              </p>
              {!spouse ? (
                <div className="family-add-row">
                  <input
                    className="family-name-input"
                    value={personName}
                    onChange={(e) => setPersonName(e.target.value)}
                    placeholder="배우자 성함 (선택)"
                    disabled={busy}
                  />
                  <Button
                    disabled={busy}
                    onClick={async () => {
                      if (await add("spouse", personName)) {
                        setPersonName("");
                        setPhase("children");
                      }
                    }}
                  >
                    배우자 추가
                  </Button>
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() => {
                      setPersonName("");
                      setPhase("children");
                    }}
                  >
                    배우자 없음
                  </Button>
                </div>
              ) : (
                <div className="family-added-line">
                  <span>
                    배우자 · <strong>{spouse.name}</strong>
                  </span>
                  <button
                    type="button"
                    className="family-remove"
                    disabled={busy}
                    onClick={() => removeMember(spouse.id)}
                  >
                    삭제
                  </button>
                  <Button disabled={busy} onClick={() => setPhase("children")}>
                    다음
                  </Button>
                </div>
              )}
            </>
          )}

          {/* 2) 자녀 */}
          {phase === "children" && (
            <>
              <p className="intake-question">자녀를 한 분씩 추가해 주세요</p>
              {children.length > 0 && (
                <ul className="family-list">
                  {children.map((c, i) => (
                    <li key={c.id}>
                      <span>
                        {ORDINAL[i] ?? `${i + 1}번째`} · <strong>{c.name}</strong>
                        {c.is_minor && (
                          <span className="family-tag">미성년</span>
                        )}
                      </span>
                      <button
                        type="button"
                        className="family-remove"
                        disabled={busy}
                        onClick={() => removeMember(c.id)}
                      >
                        삭제
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <div className="family-add-row">
                <input
                  className="family-name-input"
                  value={childName}
                  onChange={(e) => setChildName(e.target.value)}
                  placeholder={`${ORDINAL[children.length] ?? `${children.length + 1}번째`} 자녀 성함 (선택)`}
                  disabled={busy}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                      void (async () => {
                        if (await add("child", childName, childMinor)) {
                          setChildName("");
                          setChildMinor(false);
                        }
                      })();
                    }
                  }}
                />
                <label className="family-minor-check">
                  <input
                    type="checkbox"
                    checked={childMinor}
                    onChange={(e) => setChildMinor(e.target.checked)}
                    disabled={busy}
                  />
                  미성년
                </label>
                <Button
                  disabled={busy}
                  onClick={async () => {
                    if (await add("child", childName, childMinor)) {
                      setChildName("");
                      setChildMinor(false);
                    }
                  }}
                >
                  자녀 추가
                </Button>
              </div>
              <div className="intake-actions">
                {children.length === 0 ? (
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() => setPhase("parents")}
                  >
                    자녀 없음
                  </Button>
                ) : (
                  <Button disabled={busy} onClick={done}>
                    완료하고 상담 시작
                  </Button>
                )}
              </div>
            </>
          )}

          {/* 3) 부모 (자녀가 없을 때만 상속 순위상 의미가 있음) */}
          {phase === "parents" && (
            <>
              <p className="intake-question">
                {centerNoun === "나" ? "부모님이 생존해 계세요?" : `${centerNoun}의 부모님이 생존해 계신가요?`}
              </p>
              {parents.length === 0 ? (
                <div className="family-add-row">
                  <input
                    className="family-name-input"
                    value={personName}
                    onChange={(e) => setPersonName(e.target.value)}
                    placeholder="부모님 성함 (선택)"
                    disabled={busy}
                  />
                  <Button
                    disabled={busy}
                    onClick={async () => {
                      if (await add("parent", personName)) {
                        setPersonName("");
                        done();
                      }
                    }}
                  >
                    부모님 추가
                  </Button>
                  <Button variant="outline" disabled={busy} onClick={done}>
                    안 계세요
                  </Button>
                </div>
              ) : (
                <div className="family-added-line">
                  <span>
                    부모 · <strong>{parents[0].name}</strong>
                  </span>
                  <Button disabled={busy} onClick={done}>
                    완료하고 상담 시작
                  </Button>
                </div>
              )}
            </>
          )}
        </div>

        <button type="button" className="onboarding-skip" onClick={done}>
          건너뛰고 상담 시작하기
        </button>
      </div>
    </div>
  );
}
