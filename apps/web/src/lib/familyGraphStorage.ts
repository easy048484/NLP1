/**
 * family_graph_id와 인테이크 진행 상태를 localStorage에 보관합니다.
 *
 * apps/api/family_graph/models.py 상단 docstring대로, 가족관계 정보는
 * 대화 세션(오케스트레이터의 ChatSession, 2시간 TTL)보다 오래 살아야
 * 하므로 세션 상태와 완전히 분리해서 이 모듈에서만 관리합니다.
 *
 * 프라이빗 브라우징 등 localStorage 접근이 막힌 환경에서도 앱이 죽지
 * 않도록 모든 호출을 try/catch로 감쌉니다 — 실패하면 그 세션 동안은
 * 그냥 다시 못 불러올 뿐(새로고침하면 처음부터 다시 물어봄)이고, 완전한
 * 장애로 취급하지 않습니다.
 */

const FAMILY_GRAPH_ID_KEY = "nlp1.family_graph_id";
const INTAKE_PROGRESS_KEY = "nlp1.family_graph_intake_progress";
const INTAKE_ANSWERS_KEY = "nlp1.family_graph_intake_answers";

/**
 * 인테이크가 지금 어디까지 진행됐는지를 나타냅니다.
 * - 질문 단계 id("children_count" 등): 그 질문부터 이어서 보여줘야 함.
 * - "complete": 다 끝남, 다시 묻지 않음.
 * - "declined": 사용자가 "다음에 할게요"를 선택함, 헤더 진입점에서만 다시 시작.
 */
export type IntakeProgress =
  | "spouse"
  | "children_count"
  | "children_minor"
  | "parents"
  | "complete"
  | "declined";

export function getFamilyGraphId(): string | null {
  try {
    return window.localStorage.getItem(FAMILY_GRAPH_ID_KEY);
  } catch {
    return null;
  }
}

export function setFamilyGraphId(id: string): void {
  try {
    window.localStorage.setItem(FAMILY_GRAPH_ID_KEY, id);
  } catch {
    // 저장 실패해도 이번 세션은 메모리 state로 계속 진행합니다.
  }
}

export function clearFamilyGraphId(): void {
  try {
    window.localStorage.removeItem(FAMILY_GRAPH_ID_KEY);
  } catch {
    // ignore
  }
}

export function getIntakeProgress(): IntakeProgress | null {
  try {
    return window.localStorage.getItem(INTAKE_PROGRESS_KEY) as IntakeProgress | null;
  } catch {
    return null;
  }
}

export function setIntakeProgress(step: IntakeProgress): void {
  try {
    window.localStorage.setItem(INTAKE_PROGRESS_KEY, step);
  } catch {
    // ignore
  }
}

export function clearIntakeProgress(): void {
  try {
    window.localStorage.removeItem(INTAKE_PROGRESS_KEY);
  } catch {
    // ignore
  }
}

/**
 * 인테이크 도중 답한 값(배우자 유무 등)의 캐시입니다. 다음 질문을 결정하는
 * 분기 로직(familyIntakeFlow.ts의 getNextStep)이 이 값을 필요로 하는데,
 * "배우자 없음"처럼 서버에 구성원이 아예 안 생기는 답변은 family_graph
 * 조회만으로는 복원할 수 없어서(구성원이 없는 게 "안 물어봄"인지 "없다고
 * 답함"인지 구분이 안 됨) 별도로 저장해둡니다.
 */
export interface StoredIntakeAnswers {
  spouseAlive: boolean | null;
  childrenCount: number | null;
  minorChildrenCount: number | null;
  parentsAlive: boolean | null;
}

export function getIntakeAnswers(): StoredIntakeAnswers | null {
  try {
    const raw = window.localStorage.getItem(INTAKE_ANSWERS_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as StoredIntakeAnswers;
  } catch {
    return null;
  }
}

export function setIntakeAnswers(answers: StoredIntakeAnswers): void {
  try {
    window.localStorage.setItem(INTAKE_ANSWERS_KEY, JSON.stringify(answers));
  } catch {
    // ignore
  }
}

export function clearIntakeAnswers(): void {
  try {
    window.localStorage.removeItem(INTAKE_ANSWERS_KEY);
  } catch {
    // ignore
  }
}
