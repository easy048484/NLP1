import { useEffect, useState } from "react";
import {
  addFamilyMember,
  createFamilyGraph,
  deleteFamilyMember,
  getFamilyGraph,
  updateFamilyMember,
} from "../lib/familyGraph";
import { setFamilyGraphId as persistFamilyGraphId } from "../lib/familyGraphStorage";
import type { FamilyMemberOut, RelationType } from "../types";

/**
 * apps/api/agents/heir_navigator/consent.py 의 _RELATION_LABELS와 맞춘
 * 한글 라벨입니다. family_graph_입력_플로우_계획_0823.md 3절 질문 설계는
 * 배우자·자녀·부모만 다루지만, 이 관리 패널에서는 6종 관계를 전부 추가할
 * 수 있게 열어둡니다 — 인테이크가 다루지 않는 형제자매·조부모·손자녀
 * 케이스가 실제로 필요한 사용자를 위한 탈출구입니다.
 */
const RELATION_LABELS: Record<RelationType, string> = {
  spouse: "배우자",
  child: "자녀",
  parent: "부모",
  grandchild: "손자녀",
  sibling: "형제자매",
  grandparent: "조부모",
};

const RELATION_OPTIONS = Object.keys(RELATION_LABELS) as RelationType[];

/**
 * 이름 입력창을 떠날 때 서버에 PATCH를 보낼지 결정합니다.
 *
 * `savedName`은 마지막에 서버가 알고 있는 이름이어야 합니다. 타이핑 중에
 * 그 값을 같이 바꿔 버리면, blur 때 "지금 값 === 저장된 값"이 되어
 * 저장 요청이 영원히 안 나갑니다.
 */
function decideNameSave(
  savedName: string,
  draft: string,
): { save: false } | { save: true; name: string } {
  const name = draft.trim();
  if (!name || name === savedName) {
    return { save: false };
  }
  return { save: true, name };
}

/**
 * 헤더의 "가족 구성원" 버튼으로 여는 상시 관리 패널. 조회(GET)·추가(POST)·
 * 수정(PATCH)·삭제(DELETE)를 전부 지원합니다 — family_graph_입력_플로우_
 * 계획_0823.md 12절 결정사항(수정/삭제 API 추가)과 6-1절 참고.
 */
export function FamilyGraphPanel({
  familyGraphId,
  onFamilyGraphIdChange,
  onClose,
}: {
  familyGraphId: string | null;
  onFamilyGraphIdChange: (id: string) => void;
  onClose: () => void;
}) {
  const [members, setMembers] = useState<FamilyMemberOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyMemberId, setBusyMemberId] = useState<number | null>(null);

  const [newName, setNewName] = useState("");
  const [newRelation, setNewRelation] = useState<RelationType>("spouse");
  const [newIsMinor, setNewIsMinor] = useState(false);
  const [addingMember, setAddingMember] = useState(false);
  /** 입력 중인 이름. 서버에 확정된 값(member.name)과 분리한다. */
  const [draftNames, setDraftNames] = useState<Record<number, string>>({});

  const clearDraftName = (memberId: number) => {
    setDraftNames((prev) => {
      if (!(memberId in prev)) return prev;
      const next = { ...prev };
      delete next[memberId];
      return next;
    });
  };

  useEffect(() => {
    let cancelled = false;

    async function load() {
      if (!familyGraphId) {
        setMembers([]);
        return;
      }
      const res = await getFamilyGraph(familyGraphId);
      if (cancelled) return;
      if (res.ok && res.data) {
        setMembers(res.data.members);
      } else {
        setError(res.errorMessage ?? "가족 구성원 정보를 불러오지 못했어요.");
        setMembers([]);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [familyGraphId]);

  const refreshFromServer = async (graphId: string) => {
    const res = await getFamilyGraph(graphId);
    if (res.ok && res.data) {
      setMembers(res.data.members);
    }
  };

  const handleUpdate = async (
    member: FamilyMemberOut,
    patch: Partial<Pick<FamilyMemberOut, "name" | "is_minor" | "is_alive">>,
  ) => {
    if (!familyGraphId) return;
    setBusyMemberId(member.id);
    setError(null);

    const res = await updateFamilyMember(familyGraphId, member.id, patch);
    if (res.ok && res.data) {
      setMembers((prev) =>
        (prev ?? []).map((m) => (m.id === member.id ? (res.data as FamilyMemberOut) : m)),
      );
    } else {
      setError(res.errorMessage ?? "수정하지 못했어요.");
      await refreshFromServer(familyGraphId);
    }
    setBusyMemberId(null);
  };

  const commitMemberName = async (member: FamilyMemberOut, rawDraft: string) => {
    const decision = decideNameSave(member.name, rawDraft);
    if (!decision.save) {
      clearDraftName(member.id);
      return;
    }
    await handleUpdate(member, { name: decision.name });
    clearDraftName(member.id);
  };

  const handleDelete = async (member: FamilyMemberOut) => {
    if (!familyGraphId) return;
    setBusyMemberId(member.id);
    setError(null);

    const res = await deleteFamilyMember(familyGraphId, member.id);
    if (res.ok) {
      setMembers((prev) => (prev ?? []).filter((m) => m.id !== member.id));
    } else {
      setError(res.errorMessage ?? "삭제하지 못했어요.");
      await refreshFromServer(familyGraphId);
    }
    setBusyMemberId(null);
  };

  const handleAdd = async () => {
    setAddingMember(true);
    setError(null);

    let graphId = familyGraphId;
    if (!graphId) {
      const created = await createFamilyGraph();
      if (!created.ok || !created.data) {
        setError(created.errorMessage ?? "가족 구성원 정보를 저장하지 못했어요.");
        setAddingMember(false);
        return;
      }
      graphId = created.data.id;
      persistFamilyGraphId(graphId);
      onFamilyGraphIdChange(graphId);
    }

    const res = await addFamilyMember(graphId, {
      name: newName.trim() || RELATION_LABELS[newRelation],
      relation: newRelation,
      is_alive: true,
      is_minor: newIsMinor,
    });

    if (res.ok && res.data) {
      setMembers((prev) => [...(prev ?? []), res.data as FamilyMemberOut]);
      setNewName("");
      setNewIsMinor(false);
    } else {
      setError(res.errorMessage ?? "구성원을 추가하지 못했어요.");
    }
    setAddingMember(false);
  };

  return (
    <div className="family-panel-overlay" onClick={onClose}>
      <div className="family-panel" onClick={(e) => e.stopPropagation()}>
        <div className="family-panel-header">
          <h2>가족 구성원</h2>
          <button type="button" className="icon-btn" onClick={onClose}>
            닫기
          </button>
        </div>

        {members === null && <div className="family-panel-empty">불러오는 중...</div>}

        {members !== null && members.length === 0 && (
          <div className="family-panel-empty">
            아직 등록된 가족 구성원이 없어요. 아래에서 추가해주세요.
          </div>
        )}

        {members?.map((member) => (
          <div className="family-panel-member" key={member.id}>
            <div className="family-panel-member-main">
              <div className="family-panel-member-name">
                <input
                  type="text"
                  value={draftNames[member.id] ?? member.name}
                  onChange={(e) =>
                    setDraftNames((prev) => ({
                      ...prev,
                      [member.id]: e.target.value,
                    }))
                  }
                  onBlur={(e) => {
                    void commitMemberName(member, e.currentTarget.value);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      e.currentTarget.blur();
                    }
                  }}
                  disabled={busyMemberId === member.id}
                />
              </div>
              <div className="family-panel-member-meta">
                <span>{RELATION_LABELS[member.relation]}</span>
                <label>
                  <input
                    type="checkbox"
                    checked={member.is_minor}
                    disabled={busyMemberId === member.id}
                    onChange={(e) => handleUpdate(member, { is_minor: e.target.checked })}
                  />
                  미성년
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={member.is_alive}
                    disabled={busyMemberId === member.id}
                    onChange={(e) => handleUpdate(member, { is_alive: e.target.checked })}
                  />
                  생존
                </label>
              </div>
            </div>
            <button
              type="button"
              className="family-panel-delete-btn"
              disabled={busyMemberId === member.id}
              onClick={() => handleDelete(member)}
            >
              삭제
            </button>
          </div>
        ))}

        {error && <div className="intake-error">{error}</div>}

        <div className="family-panel-add-form">
          <div className="family-panel-add-row">
            <select
              value={newRelation}
              onChange={(e) => setNewRelation(e.target.value as RelationType)}
            >
              {RELATION_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {RELATION_LABELS[r]}
                </option>
              ))}
            </select>
            <input
              type="text"
              placeholder="이름 (생략 가능)"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
          </div>
          <div className="family-panel-add-row">
            <label>
              <input
                type="checkbox"
                checked={newIsMinor}
                onChange={(e) => setNewIsMinor(e.target.checked)}
              />
              미성년
            </label>
            <button
              type="button"
              className="send-btn"
              onClick={handleAdd}
              disabled={addingMember}
            >
              + 구성원 추가
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
