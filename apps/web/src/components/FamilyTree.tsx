import type { FamilyMemberOut } from "../types";

/**
 * 가족관계 시각화. 피상속인(나/고인)을 중앙에 두고 배우자는 점선, 자녀는 실선으로.
 * (docs/가족그래프_개편_설계안.html 와이어프레임 구조)
 *
 * 데이터 입력은 인테이크/관리 시트가 담당하고, 이 컴포넌트는 표시 전용이다.
 */
export function FamilyTree({
  members,
  centerLabel = "피상속인",
}: {
  members: FamilyMemberOut[];
  centerLabel?: string;
}) {
  const spouse = members.find((m) => m.relation === "spouse");
  const children = members.filter((m) => m.relation === "child");
  const parents = members.filter((m) => m.relation === "parent");
  const others = members.filter(
    (m) => !["spouse", "child", "parent"].includes(m.relation),
  );

  return (
    <div className="family-tree" role="img" aria-label={describeTree(members, centerLabel)}>
      {parents.length > 0 && (
        <div className="ft-row ft-parents">
          {parents.map((p) => (
            <Node key={p.id} member={p} kind="parent" />
          ))}
        </div>
      )}
      {parents.length > 0 && <div className="ft-connector ft-vert" />}

      <div className="ft-row ft-center-row">
        <div className="ft-center-node">
          <span className="ft-node-rel">{centerLabel}</span>
          <span className="ft-node-name">기준</span>
        </div>
        {spouse && (
          <>
            <div className="ft-connector ft-horiz ft-dashed" />
            <Node member={spouse} kind="spouse" />
          </>
        )}
      </div>

      {children.length > 0 && (
        <>
          <div className="ft-connector ft-vert" />
          <div className="ft-row ft-children">
            {children.map((c) => (
              <Node key={c.id} member={c} kind="child" />
            ))}
          </div>
        </>
      )}

      {others.length > 0 && (
        <div className="ft-row ft-others">
          {others.map((o) => (
            <Node key={o.id} member={o} kind="other" />
          ))}
        </div>
      )}

      {members.length === 0 && (
        <p className="ft-empty">아래 질문에 답하시면 가족관계가 여기에 그려집니다.</p>
      )}
    </div>
  );
}

const REL_LABEL: Record<string, string> = {
  spouse: "배우자",
  child: "자녀",
  parent: "부모",
  grandchild: "손자녀",
  sibling: "형제자매",
  grandparent: "조부모",
};

function Node({
  member,
  kind,
}: {
  member: FamilyMemberOut;
  kind: "spouse" | "child" | "parent" | "other";
}) {
  return (
    <div className={`ft-node ft-node-${kind}${!member.is_alive ? " ft-node-deceased" : ""}`}>
      <span className="ft-node-rel">{REL_LABEL[member.relation] ?? member.relation}</span>
      <span className="ft-node-name">{member.name}</span>
      {member.is_minor && <span className="ft-node-tag">미성년</span>}
      {!member.is_alive && <span className="ft-node-tag">사망</span>}
    </div>
  );
}

function describeTree(members: FamilyMemberOut[], center: string): string {
  if (members.length === 0) return `${center} 기준, 등록된 가족 없음`;
  const parts = members.map((m) => `${REL_LABEL[m.relation] ?? m.relation} ${m.name}`);
  return `${center} 기준 가족관계도: ${parts.join(", ")}`;
}
