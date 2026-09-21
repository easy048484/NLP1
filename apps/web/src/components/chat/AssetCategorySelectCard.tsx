import { useState } from "react";
import { Button, Card } from "../ui";
import { ASSET_CATEGORY_OPTIONS } from "../../lib/assetCategories";

/**
 * asset_organizer 자산정리 진입/추가 카테고리 다중 선택 UI.
 *
 * 시작 의사만 있고 구체적 항목이 없을 때(agent.py의 awaiting_category_selection)와
 * 남은 카테고리 확인에서 "더 있어요"를 눌렀을 때(RemainingCategoriesPrompt)
 * 같은 상호작용이라 이 컴포넌트를 함께 쓴다.
 *
 * `availableKeys`가 있으면 그 안의 카테고리만 보여주고(pending_categories로
 * 좁혀진 재표시), 생략하면 전체 목록을 보여준다(최초 진입). "기타"는 백엔드
 * 체크리스트에 없는 catch-all이라 availableKeys와 무관하게 항상 선택 가능하다.
 */
export function AssetCategorySelectCard({
  availableKeys,
  onSubmit,
  disabled = false,
}: {
  availableKeys?: string[];
  onSubmit: (selectedKeys: string[]) => void;
  /** 응답 대기 중(loading) 등 제출 자체를 잠깐 막아야 할 때. */
  disabled?: boolean;
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
        <Button onClick={handleSubmit} disabled={selected.size === 0 || disabled}>
          선택 완료
        </Button>
      </div>
    </Card>
  );
}
