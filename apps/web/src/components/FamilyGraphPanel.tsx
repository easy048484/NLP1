import { useEffect, useState } from "react";
import {
  addFamilyMember,
  createFamilyGraph,
  deleteFamilyMember,
  getFamilyGraph,
  updateFamilyMember,
} from "../lib/familyGraph";
import { setFamilyGraphId as persistFamilyGraphId } from "../lib/familyGraphStorage";
import { RELATION_LABELS, RELATION_OPTIONS } from "../lib/relations";
import type { FamilyGraphOut, FamilyMemberOut, RelationType } from "../types";
import { Button, Dialog } from "./ui";

function decideNameSave(
  savedName: string,
  draft: string,
): { save: false } | { save: true; name: string } {
  const name = draft.trim();
  if (!name || name === savedName) return { save: false };
  return { save: true, name };
}

/**
 * 헤더/컨텍스트 패널의 "가족 구성원 수정"으로 여는 관리 시트.
 * 조회·추가·수정·삭제 전부 지원. 인테이크가 안 다루는 형제자매·조부모·손자녀도 여기서.
 */
export function FamilyGraphPanel({
  familyGraphId,
  onFamilyGraphIdChange,
  onGraphChange,
  onClose,
}: {
  familyGraphId: string | null;
  onFamilyGraphIdChange: (id: string) => void;
  onGraphChange: (graph: FamilyGraphOut | null) => void;
  onClose: () => void;
}) {
  const [members, setMembers] = useState<FamilyMemberOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyMemberId, setBusyMemberId] = useState<number | null>(null);
  const [newName, setNewName] = useState("");
  const [newRelation, setNewRelation] = useState<RelationType>("spouse");
  const [newIsMinor, setNewIsMinor] = useState(false);
  const [addingMember, setAddingMember] = useState(false);
  const [draftNames, setDraftNames] = useState<Record<number, string>>({});

  const clearDraftName = (memberId: number) =>
    setDraftNames((prev) => {
      if (!(memberId in prev)) return prev;
      const next = { ...prev };
      delete next[memberId];
      return next;
    });

  const pushGraph = (next: FamilyMemberOut[]) => {
    setMembers(next);
    if (familyGraphId) {
      onGraphChange({
        id: familyGraphId,
        created_at: new Date().toISOString(),
        members: next,
      });
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!familyGraphId) {
        setMembers([]);
        return;
      }
      const res = await getFamilyGraph(familyGraphId);
      if (cancelled) return;
      if (res.ok && res.data) {
        setMembers(res.data.members);
        onGraphChange(res.data);
      } else {
        setError(res.errorMessage ?? "가족 구성원 정보를 불러오지 못했어요.");
        setMembers([]);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [familyGraphId]);

  const handleUpdate = async (
    member: FamilyMemberOut,
    patch: Partial<Pick<FamilyMemberOut, "name" | "is_minor" | "is_alive">>,
  ) => {
    if (!familyGraphId) return;
    setBusyMemberId(member.id);
    setError(null);
    const res = await updateFamilyMember(familyGraphId, member.id, patch);
    if (res.ok && res.data) {
      pushGraph((members ?? []).map((m) => (m.id === member.id ? res.data! : m)));
    } else {
      setError(res.errorMessage ?? "수정하지 못했어요.");
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
      pushGraph((members ?? []).filter((m) => m.id !== member.id));
    } else {
      setError(res.errorMessage ?? "삭제하지 못했어요.");
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
      setMembers((prev) => {
        const next = [...(prev ?? []), res.data!];
        onGraphChange({
          id: graphId!,
          created_at: new Date().toISOString(),
          members: next,
        });
        return next;
      });
      setNewName("");
      setNewIsMinor(false);
    } else {
      setError(res.errorMessage ?? "구성원을 추가하지 못했어요.");
    }
    setAddingMember(false);
  };

  return (
    <Dialog title="가족 구성원" variant="sheet" onClose={onClose}>
      {members === null && <p className="fp-note">불러오는 중…</p>}
      {members?.length === 0 && (
        <p className="fp-note">아직 등록된 가족 구성원이 없어요. 아래에서 추가해 주세요.</p>
      )}

      <ul className="fp-member-list">
        {members?.map((member) => (
          <li className="fp-member" key={member.id}>
            <div className="fp-member-main">
              <input
                className="fp-member-name"
                type="text"
                aria-label="이름"
                value={draftNames[member.id] ?? member.name}
                onChange={(e) =>
                  setDraftNames((prev) => ({ ...prev, [member.id]: e.target.value }))
                }
                onBlur={(e) => void commitMemberName(member, e.currentTarget.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    e.currentTarget.blur();
                  }
                }}
                disabled={busyMemberId === member.id}
              />
              <div className="fp-member-meta">
                <span className="fp-rel">{RELATION_LABELS[member.relation]}</span>
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
              className="fp-delete"
              disabled={busyMemberId === member.id}
              onClick={() => handleDelete(member)}
            >
              삭제
            </button>
          </li>
        ))}
      </ul>

      {error && <p className="fp-error" role="alert">⚠ {error}</p>}

      <div className="fp-add">
        <div className="fp-add-row">
          <select
            aria-label="관계"
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
            aria-label="이름"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
        </div>
        <div className="fp-add-row">
          <label>
            <input
              type="checkbox"
              checked={newIsMinor}
              onChange={(e) => setNewIsMinor(e.target.checked)}
            />
            미성년
          </label>
          <Button onClick={handleAdd} disabled={addingMember}>
            + 구성원 추가
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
