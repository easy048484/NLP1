/**
 * asset_organizer 카테고리 선택 UI(AssetCategorySelectCard)가 쓰는 고정
 * 카테고리 목록 — 표시 라벨과 백엔드가 이해하는 실제 키워드를 함께 담는다.
 *
 * 순서가 그대로 제출 순서다: "선택 완료" 시 이 배열 순서대로 라벨을 나열한
 * 문장을 만들어 보내면, 백엔드 extractor.py의 키워드 매칭이 세그먼트
 * 순서를 그대로 따라가 pending_amounts도 이 순서로 쌓인다(_regex_extract가
 * 자산 세그먼트를 먼저, extract_liabilities가 부채를 뒤에 처리하므로 "부채"
 * 는 항상 맨 뒤에 둔다 — agent.py._merge_extraction 참고).
 *
 * "기타"는 백엔드 체크리스트 카테고리(_ALL_CATEGORIES)에 없는
 * catch-all이라(agent.py 주석: "특정 유형 없이 뭉뚱그려 말한 항목을 담는
 * 그릇") 선택해도 구조화된 카테고리 확인 대상이 되지 않는다 — 선택 시
 * 별도로 자유 입력을 유도한다(AssetCategorySelectCard 참고).
 */
export interface AssetCategoryOption {
  /** 백엔드 checked_categories/pending_categories와 비교하는 실제 키. */
  key: string;
  /** 화면에 보여줄 라벨. */
  label: string;
}

export const ASSET_CATEGORY_OPTIONS: AssetCategoryOption[] = [
  { key: "예금", label: "예금·적금" },
  { key: "주식", label: "주식" },
  { key: "펀드", label: "펀드" },
  { key: "부동산", label: "부동산" },
  { key: "자동차", label: "자동차" },
  { key: "퇴직연금", label: "퇴직연금" },
  { key: "보험", label: "보험" },
  { key: "기타", label: "기타" },
  { key: "부채", label: "대출·기타 부채" },
];

/** 백엔드 checked_categories/pending_categories가 실제로 추적하는 키만
 * (기타 제외) — awaiting_category_selection 트리거 시 "아직 확인 안 된"
 * 전체 목록을 계산하는 데 쓴다. */
export const TRACKED_ASSET_CATEGORY_KEYS: string[] = ASSET_CATEGORY_OPTIONS.filter(
  (c) => c.key !== "기타",
).map((c) => c.key);

export function labelFor(key: string): string {
  return ASSET_CATEGORY_OPTIONS.find((c) => c.key === key)?.label ?? key;
}

/**
 * 선택된 카테고리 키들로 백엔드가 이해할 자연어 제출 문장을 만든다.
 * ASSET_CATEGORY_OPTIONS 순서(자산 먼저, 부채 마지막)를 그대로 따르므로
 * 클릭 순서와 무관하게 항상 같은 순서로 pending_amounts가 쌓인다.
 *
 * "기타"는 문장에서 제외한다 — 대응하는 키워드가 없어 extractor.py가
 * 이해할 수 없고(_ASSET_KEYWORDS/_LIABILITY_KEYWORDS 어디에도 없음),
 * 억지로 넣으면 그 세그먼트만 "이해 못함"으로 남아 다른 선택 항목과
 * 섞여 혼란만 준다.
 */
export function composeCategorySelectionMessage(selectedKeys: string[]): string {
  const labels = ASSET_CATEGORY_OPTIONS.filter(
    (c) => c.key !== "기타" && selectedKeys.includes(c.key),
  ).map((c) => c.label);
  if (labels.length === 0) return "";
  return `${labels.join(", ")}을(를) 정리할게요.`;
}
