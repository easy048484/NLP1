import type { RelationType } from "../types";

/**
 * apps/api/agents/heir_navigator/consent.py 의 _RELATION_LABELS 와 맞춘 한글 라벨.
 * 가족관계증명서·안심상속 원스톱 서식의 용어를 그대로 쓴다.
 */
export const RELATION_LABELS: Record<RelationType, string> = {
  spouse: "배우자",
  child: "자녀",
  parent: "부모",
  grandchild: "손자녀",
  sibling: "형제자매",
  grandparent: "조부모",
};

export const RELATION_OPTIONS = Object.keys(RELATION_LABELS) as RelationType[];
