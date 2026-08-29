import type { FamilyMemberIn, RelationType } from "../types";

/**
 * family_graph 인테이크 질문 순서를 데이터로 정의합니다.
 * (family_graph_입력_플로우_계획_0823.md 3절 질문 설계 표 그대로)
 *
 * React 컴포넌트(FamilyIntake.tsx)와 분리된 순수 함수/상수만 모아뒀습니다 —
 * 백엔드나 브라우저 없이도 이 파일만으로 분기 로직을 테스트할 수 있습니다.
 *
 * MVP 범위는 배우자·자녀·(필요할 때만) 부모입니다. 형제자매·조부모·
 * 손자녀(대습상속)는 이번 범위에서 제외했습니다 — 이유는 계획 문서 12절
 * 참고(상속 순위 조건부 분기가 트리 구조로 복잡해지고, tax_calculator의
 * 대습상속 분류 버그가 아직 안 고쳐진 상태라 정확한 계산을 보장할 수
 * 없기 때문).
 */

export type IntakeStepId =
  | "spouse"
  | "children_count"
  | "children_minor"
  | "parents"
  | "complete";

export interface IntakeAnswers {
  spouseAlive: boolean | null;
  childrenCount: number | null;
  minorChildrenCount: number | null;
  parentsAlive: boolean | null;
}

export const EMPTY_ANSWERS: IntakeAnswers = {
  spouseAlive: null,
  childrenCount: null,
  minorChildrenCount: null,
  parentsAlive: null,
};

/** "3"은 UI에 "3명 이상"으로 표시됩니다 — 정확한 대량 가족 구성은 관리 패널에서 추가. */
export const CHILDREN_COUNT_OPTIONS = [0, 1, 2, 3] as const;

export const SPOUSE_QUESTION =
  "가족 구성원을 몇 가지만 여쭤볼게요. 배우자가 생존해 계신가요?";
export const CHILDREN_COUNT_QUESTION = "생존해 계신 자녀는 몇 분인가요?";
export const CHILDREN_MINOR_QUESTION =
  "그중 미성년(만 19세 미만) 자녀가 있다면 몇 분인가요?";
export const PARENTS_QUESTION =
  "자녀분이 안 계시면, 돌아가신 분의 부모님이 생존해 계신가요?";
export const COMPLETE_MESSAGE =
  "가족 구성원 정보를 저장했어요. 앞으로 관련 질문은 건너뛸게요. 필요하면 헤더의 " +
  "'가족 구성원'에서 언제든 다시 확인하거나 수정할 수 있어요.";

function childCountLabel(n: number): string {
  return n === 3 ? "3명 이상" : `${n}명`;
}

export function childrenCountOptionLabel(n: number): string {
  return childCountLabel(n);
}

/**
 * 현재 답변까지 반영했을 때 다음에 물어볼 질문을 결정합니다.
 *
 * 분기 규칙:
 * - spouse 다음은 항상 children_count.
 * - children_count > 0 이면 children_minor로.
 * - children_count === 0 이고 배우자가 있으면(공동상속 여부를 가리기 위해)
 *   parents로 — 안 물어보면 tax_calculator의 spouse_is_sole_heir가 기본값
 *   False로 남아 계산이 실패하는 케이스와 동일한 이유입니다
 *   (apps/api/agents/tax_calculator/agent.py의 _missing_slots 참고).
 * - 그 외(children_count === 0이고 배우자도 없음)엔 더 물어볼 게 없어 바로 complete.
 * - children_minor/parents 다음은 항상 complete.
 */
export function getNextStep(
  current: IntakeStepId,
  answers: IntakeAnswers,
): IntakeStepId {
  switch (current) {
    case "spouse":
      return "children_count";
    case "children_count":
      if ((answers.childrenCount ?? 0) > 0) {
        return "children_minor";
      }
      return answers.spouseAlive === true ? "parents" : "complete";
    case "children_minor":
      return "complete";
    case "parents":
      return "complete";
    case "complete":
      return "complete";
  }
}

/** 배우자 "네" 답변 시 저장할 구성원. */
export function buildSpouseMember(): FamilyMemberIn {
  return { name: "배우자", relation: "spouse" as RelationType, is_alive: true };
}

/** 자녀 수만큼 만들 구성원 목록(전부 is_minor: false로 시작, 미성년 답변 후 PATCH). */
export function buildChildMembers(count: number): FamilyMemberIn[] {
  return Array.from({ length: count }, (_, i) => ({
    name: `자녀 ${i + 1}`,
    relation: "child" as RelationType,
    is_alive: true,
    is_minor: false,
  }));
}

/** 부모님 생존 "네" 답변 시 저장할 구성원(정확한 인원수는 묻지 않고 1명으로 대표). */
export function buildParentMember(): FamilyMemberIn {
  return { name: "부모님", relation: "parent" as RelationType, is_alive: true };
}

/**
 * 재방문(이어하기) 시 현재 단계 질문 위에 보여줄 한 줄 요약.
 * 처음 시작하는 경우(phase === "spouse")에는 보여줄 이전 답변이 없으므로 null.
 */
export function resumeIntroLine(
  phase: IntakeStepId,
  answers: IntakeAnswers,
): string | null {
  if (phase === "spouse") return null;

  const parts: string[] = [];
  if (answers.spouseAlive === true) parts.push("배우자 있음");
  if (answers.spouseAlive === false) parts.push("배우자 없음");
  if (typeof answers.childrenCount === "number") {
    parts.push(`자녀 ${childCountLabel(answers.childrenCount)}`);
  }
  if (typeof answers.minorChildrenCount === "number") {
    parts.push(`그중 미성년 ${answers.minorChildrenCount}명`);
  }

  if (parts.length === 0) return null;
  return `${parts.join(", ")} — 이어서 알려주시겠어요?`;
}
