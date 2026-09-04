import { useState } from "react";
import { Button, Card } from "../ui";
import { ASSET_CATEGORY_OPTIONS } from "../../lib/assetCategories";

/**
 * asset_organizer 자산정리 진입/추가 카테고리 다중 선택 UI.
 *
 * "자산 정리하고 싶어요"처럼 시작 의사만 있고 구체적 항목이 없을 때
 * (agent.py의 awaiting_category_selection), 또는 남은 카테고리 일괄
 * 확인에서 "더 있어요"를 눌렀을 때(RemainingCategoriesPrompt) 재사용한다
 * — 둘 다 "카테고리 몇 개를 골라 제출"이라는 같은 상호작용이라 로컬
 * 컴포넌트 하나로 통일했다.
 *
 * `availableKeys`가 주어지면 그 안에 있는 카테고리만 보여준다(예:
 * pending_categories로 좁혀진 "더 있어요" 재표시) — 생략하면 전체
 * 목록을 보여준다(최초 진입). "기타"는 백엔드 체크리스트에 없는
 * catch-all이라 availableKeys 필터와 무관하게 항상 선택 가능하게 둔다.
 */
export function AssetCategorySelectCard({
  availableKeys,
  onSubmit,
}: {
  availableKeys?: string[];
  onSubmit: (selectedKeys: string[]) => void;
}) {
  const options = availableKeys
    ? ASSET_CATEGORY_OPTIONS.filter(
        (c) => c.key === "기타" || availableKeys.includes(c.key),
      )
    : ASSET_CATEGORY_OPTIONS;

  const [selected, setSelected] = useState<Set<string>>(new Set());

  const toggle = (key: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const handleSubmit = () => {
    // ASSET_CATEGORY_OPTIONS 순서 그대로 — 클릭 순서와 무관하게 항상
    // 같은 순서로 제출한다(composeCategorySelectionMessage와 동일 원칙).
    const orderedSelected = ASSET_CATEGORY_OPTIONS.filter((c) =>
      selected.has(c.key),
    ).map((c) => c.key);
    onSubmit(orderedSelected);
  };

  return (
    <Card className="category-select-card">
      <p className="category-select-hint">여러 개 선택할 수 있어요.</p>
      <div className="category-select-grid" role="group" aria-label="자산·부채 카테고리 선택">
        {options.map((option) => {
          const isOn = selected.has(option.key);
          return (
            <button
              key={option.key}
              type="button"
              className={`category-select-btn${isOn ? " category-select-on" : ""}`}
              aria-pressed={isOn}
              onClick={() => toggle(option.key)}
            >
              {option.label}
            </button>
          );
        })}
      </div>
      <div className="category-select-actions">
        <Button onClick={handleSubmit} disabled={selected.size === 0}>
          선택 완료
        </Button>
      </div>
    </Card>
  );
}
