import { useEffect, useMemo, useState } from "react";
import { createFamilyTree, getFamilyTree, updateFamilyTree } from "../lib/api";
import type {
  FamilyTreeIn,
  FamilyTreeOut,
  PersonIn,
  RelationIn,
} from "../types";

/**
 * 초기 진입 온보딩 — 가족 트리 입력 화면.
 *
 * 설계 원칙 (docs/가족그래프_개편_설계안.md):
 * - 피상속인(돌아가신 분)을 중심에 두고, 카드 추가 행위가 곧 엣지 입력이 됩니다.
 * - 질문 순서는 민법 제1000조 상속 순위를 따릅니다: 배우자 → 자녀 →
 *   (자녀가 없을 때만) 부모 → (부모도 없을 때만) 형제자매. 대다수는 자녀
 *   단계에서 끝납니다 (점진적 공개).
 * - 어휘는 가족관계증명서/안심상속 서식 기준. 실명을 강제하지 않습니다.
 * - 대습상속 입력("먼저 세상을 떠난 자녀의 자녀")은 판정 엔진
 *   (family_graph/engine.py)이 없어 잠겨 있습니다 — 받아놓고 판정 못 하면
 *   잘못된 안내가 되므로, 엔진 도입 시 여는 자리만 만들어 둡니다.
 */

interface ChildEntry {
  name: string;
  isMinor: boolean;
}

interface ParentEntry {
  name: string;
  isAlive: boolean;
}

export interface FamilySetupProps {
  /** 있으면 수정 모드: 기존 트리를 불러와 프리필하고 저장 시 PUT합니다. */
  familyGraphId: string | null;
  onDone: (familyGraphId: string, memberCount: number) => void;
  onSkip: () => void;
}

const CHILD_DEFAULT_NAMES = ["첫째", "둘째", "셋째", "넷째", "다섯째"];

function childName(index: number): string {
  return CHILD_DEFAULT_NAMES[index] ?? `자녀 ${index + 1}`;
}

export function FamilySetup({ familyGraphId, onDone, onSkip }: FamilySetupProps) {
  const [hasSpouse, setHasSpouse] = useState(false);
  const [spouseAlive, setSpouseAlive] = useState(true);
  const [children, setChildren] = useState<ChildEntry[]>([]);
  const [parents, setParents] = useState<ParentEntry[]>([]);
  const [siblingCount, setSiblingCount] = useState(0);
  const [saving, setSaving] = useState(false);
  const [loadingPrefill, setLoadingPrefill] = useState(Boolean(familyGraphId));
  const [error, setError] = useState<string | null>(null);

  // 수정 모드: 저장된 트리를 위저드 상태로 되돌립니다. 이 화면이 만들 수 있는
  // 모양(배우자/자녀/부모/형제자매)만 복원하고, 그 밖의 노드는 무시합니다.
  useEffect(() => {
    if (!familyGraphId) return;
    let cancelled = false;
    getFamilyTree(familyGraphId)
      .then((tree) => {
        if (cancelled) return;
        applyPrefill(tree);
      })
      .catch(() => {
        // 프리필 실패는 치명적이지 않습니다 — 빈 폼에서 다시 입력하면 됩니다.
      })
      .finally(() => {
        if (!cancelled) setLoadingPrefill(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [familyGraphId]);

  function applyPrefill(tree: FamilyTreeOut) {
    const byId = new Map(tree.persons.map((p) => [p.id, p]));
    const decedent = tree.persons.find((p) => p.is_decedent);
    if (!decedent) return;

    const childIds = new Set<number>();
    for (const rel of tree.relations) {
      if (rel.type === "spouse_of") {
        const otherId =
          rel.from_person_id === decedent.id ? rel.to_person_id : rel.from_person_id;
        const spouse = byId.get(otherId);
        if (spouse && (rel.from_person_id === decedent.id || rel.to_person_id === decedent.id)) {
          setHasSpouse(true);
          setSpouseAlive(spouse.is_alive);
        }
      }
      if (rel.type === "parent_of" && rel.from_person_id === decedent.id) {
        childIds.add(rel.to_person_id);
      }
    }
    setChildren(
      [...childIds]
        .map((id) => byId.get(id))
        .filter((p) => p !== undefined)
        .map((p) => ({ name: p.name, isMinor: p.is_minor })),
    );

    const parentIds = tree.relations
      .filter((r) => r.type === "parent_of" && r.to_person_id === decedent.id)
      .map((r) => r.from_person_id);
    const parentPersons = parentIds
      .map((id) => byId.get(id))
      .filter((p) => p !== undefined);
    // 형제자매를 매달기 위해 자동 생성한 사망 부모 노드("부모")는 부모 입력으로
    // 복원하지 않습니다 — 저장 시 필요하면 다시 만들어집니다.
    setParents(
      parentPersons
        .filter((p) => p.is_alive)
        .map((p) => ({ name: p.name, isAlive: p.is_alive })),
    );

    const siblingIds = new Set<number>();
    for (const parentId of parentIds) {
      for (const rel of tree.relations) {
        if (
          rel.type === "parent_of" &&
          rel.from_person_id === parentId &&
          rel.to_person_id !== decedent.id
        ) {
          siblingIds.add(rel.to_person_id);
        }
      }
    }
    setSiblingCount(siblingIds.size);
  }

  const aliveParentCount = parents.filter((p) => p.isAlive).length;
  const showParentsStep = children.length === 0;
  const showSiblingsStep = children.length === 0 && aliveParentCount === 0;

  const memberCount = useMemo(() => {
    let count = (hasSpouse ? 1 : 0) + children.length;
    if (showParentsStep) count += parents.length;
    if (showSiblingsStep) count += siblingCount;
    return count;
  }, [hasSpouse, children, parents, siblingCount, showParentsStep, showSiblingsStep]);

  function buildTree(): FamilyTreeIn {
    const persons: PersonIn[] = [
      { key: "d", name: "피상속인", is_decedent: true, is_alive: false },
    ];
    const relations: RelationIn[] = [];

    if (hasSpouse) {
      persons.push({ key: "s", name: "배우자", is_alive: spouseAlive });
      relations.push({ type: "spouse_of", from_key: "d", to_key: "s" });
    }
    children.forEach((child, i) => {
      const key = `c${i}`;
      persons.push({ key, name: child.name || childName(i), is_minor: child.isMinor });
      relations.push({ type: "parent_of", from_key: "d", to_key: key });
    });
    if (showParentsStep) {
      parents.forEach((parent, i) => {
        const key = `p${i}`;
        persons.push({ key, name: parent.name, is_alive: parent.isAlive });
        relations.push({ type: "parent_of", from_key: key, to_key: "d" });
      });
    }
    if (showSiblingsStep && siblingCount > 0) {
      // 형제자매는 공통 부모를 통해 연결되는 관계라, 앵커가 될 부모 노드가
      // 필요합니다. 이 단계는 생존 부모가 없을 때만 열리므로 사망한 부모
      // 노드를 하나 만들어 매답니다 (사망자는 협의 서명자 목록에서 자동
      // 제외됩니다 — consent.py).
      persons.push({ key: "pa", name: "부모", is_alive: false });
      relations.push({ type: "parent_of", from_key: "pa", to_key: "d" });
      for (let i = 0; i < siblingCount; i += 1) {
        const key = `b${i}`;
        persons.push({ key, name: `형제자매 ${i + 1}` });
        relations.push({ type: "parent_of", from_key: "pa", to_key: key });
      }
    }
    return { persons, relations };
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const tree = buildTree();
      const saved = familyGraphId
        ? await updateFamilyTree(familyGraphId, tree)
        : await createFamilyTree(tree);
      onDone(saved.id, memberCount);
    } catch (err) {
      setError(
        err instanceof Error
          ? `저장하지 못했습니다: ${err.message}`
          : "저장하지 못했습니다. 잠시 후 다시 시도해주세요.",
      );
      setSaving(false);
    }
  }

  function setChildCount(count: number) {
    const next = Math.max(0, Math.min(count, 10));
    setChildren((prev) => {
      if (next <= prev.length) return prev.slice(0, next);
      const added = Array.from({ length: next - prev.length }, (_, i) => ({
        name: childName(prev.length + i),
        isMinor: false,
      }));
      return [...prev, ...added];
    });
  }

  if (loadingPrefill) {
    return (
      <div className="setup-shell">
        <div className="setup-card setup-loading">가족 정보를 불러오는 중…</div>
      </div>
    );
  }

  return (
    <div className="setup-shell">
      <header className="setup-header">
        <h1>가족 정보 입력</h1>
        <p>
          <strong>돌아가신 분(피상속인)을 기준으로</strong> 가족을 알려주세요.
          <br />
          입력하신 정보로 협의에 필요한 분, 기한, 세금 안내가 정확해집니다.
        </p>
      </header>

      <div className="setup-tree">
        <div className="setup-card setup-card-decedent">
          <span className="setup-card-role">피상속인</span>
          <span className="setup-card-name">돌아가신 분</span>
        </div>
      </div>

      <section className="setup-step">
        <h2>배우자가 계신가요?</h2>
        <div className="setup-toggle-row">
          <button
            type="button"
            className={`setup-toggle${hasSpouse ? " setup-toggle-on" : ""}`}
            onClick={() => setHasSpouse(true)}
          >
            있음
          </button>
          <button
            type="button"
            className={`setup-toggle${!hasSpouse ? " setup-toggle-on" : ""}`}
            onClick={() => setHasSpouse(false)}
          >
            없음
          </button>
        </div>
        {hasSpouse && (
          <label className="setup-check">
            <input
              type="checkbox"
              checked={spouseAlive}
              onChange={(e) => setSpouseAlive(e.target.checked)}
            />
            생존해 계십니다
          </label>
        )}
      </section>

      <section className="setup-step">
        <h2>자녀는 몇 분인가요?</h2>
        <div className="setup-stepper">
          <button type="button" onClick={() => setChildCount(children.length - 1)}>
            −
          </button>
          <span>{children.length}명</span>
          <button type="button" onClick={() => setChildCount(children.length + 1)}>
            +
          </button>
        </div>
        {children.map((child, i) => (
          <div className="setup-card setup-card-member" key={i}>
            <input
              className="setup-name-input"
              value={child.name}
              maxLength={20}
              onChange={(e) =>
                setChildren((prev) =>
                  prev.map((c, j) => (j === i ? { ...c, name: e.target.value } : c)),
                )
              }
              aria-label={`자녀 ${i + 1} 호칭`}
            />
            <label className="setup-check">
              <input
                type="checkbox"
                checked={child.isMinor}
                onChange={(e) =>
                  setChildren((prev) =>
                    prev.map((c, j) =>
                      j === i ? { ...c, isMinor: e.target.checked } : c,
                    ),
                  )
                }
              />
              미성년
            </label>
          </div>
        ))}
        {children.length > 0 && (
          <label className="setup-check setup-check-disabled" title="준비 중인 기능입니다">
            <input type="checkbox" disabled />
            먼저 세상을 떠난 자녀가 있어요 (준비 중)
          </label>
        )}
      </section>

      {showParentsStep && (
        <section className="setup-step">
          <h2>자녀가 없으시면, 피상속인의 부모님은요?</h2>
          <p className="setup-step-hint">
            자녀가 없으면 부모님이 상속인이 될 수 있어 여쭙니다.
          </p>
          <div className="setup-toggle-row">
            {["아버지", "어머니"].map((label) => {
              const added = parents.some((p) => p.name === label);
              return (
                <button
                  key={label}
                  type="button"
                  className={`setup-toggle${added ? " setup-toggle-on" : ""}`}
                  onClick={() =>
                    setParents((prev) =>
                      added
                        ? prev.filter((p) => p.name !== label)
                        : [...prev, { name: label, isAlive: true }],
                    )
                  }
                >
                  {label} 생존
                </button>
              );
            })}
          </div>
        </section>
      )}

      {showSiblingsStep && (
        <section className="setup-step">
          <h2>피상속인의 형제자매는 몇 분인가요?</h2>
          <p className="setup-step-hint">
            자녀와 부모님이 안 계시면 형제자매가 상속인이 될 수 있습니다.
          </p>
          <div className="setup-stepper">
            <button
              type="button"
              onClick={() => setSiblingCount((n) => Math.max(0, n - 1))}
            >
              −
            </button>
            <span>{siblingCount}명</span>
            <button
              type="button"
              onClick={() => setSiblingCount((n) => Math.min(10, n + 1))}
            >
              +
            </button>
          </div>
        </section>
      )}

      {error && <div className="setup-error">{error}</div>}

      <div className="setup-actions">
        <button type="button" className="setup-skip" onClick={onSkip} disabled={saving}>
          나중에 할게요
        </button>
        <button
          type="button"
          className="setup-save"
          onClick={handleSave}
          disabled={saving || memberCount === 0}
        >
          {saving ? "저장 중…" : `저장하고 시작하기 (${memberCount}명)`}
        </button>
      </div>
      <p className="setup-footnote">
        실명 대신 호칭만 적으셔도 됩니다. 가족관계증명서로 확인된 가족 기준으로
        안내해 드립니다.
      </p>
    </div>
  );
}
