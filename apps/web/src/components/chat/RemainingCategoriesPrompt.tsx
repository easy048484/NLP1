import { useState } from "react";
import { Button, Card } from "../ui";
import { AssetCategorySelectCard } from "./AssetCategorySelectCard";

/**
 * 선택 항목 입력이 끝난 뒤, 아직 확인하지 않은 남은 카테고리를 한 번에
 * 확인한다(agent.py의 state.pending_categories). 기존에는 "나머지는
 * 없어요" 버튼 하나뿐이었는데, 여기에 "더 있어요"를 추가해 눌렀을 때
 * AssetCategorySelectCard를 다시 보여준다(카테고리를 다시 직접 타이핑할
 * 필요 없이 남은 항목 중에서만 고르면 됨).
 *
 * "네, 모두 없어요"는 기존과 동일하게 평문 "나머지는 없어요"를 보낸다 —
 * 백엔드 _is_negative_answer()가 그대로 인식해 남은 카테고리를 전부
 * absent/checked 처리한다(agent.py 변경 없음).
 */
export function RemainingCategoriesPrompt({
  categories,
  onConfirmNone,
  onSelectMore,
}: {
  categories: string[];
  onConfirmNone: () => void;
  onSelectMore: (selectedKeys: string[]) => void;
}) {
  const [showSelect, setShowSelect] = useState(false);

  return (
    <Card className="remaining-categories-card">
      <p className="remaining-categories-question">
        아직 확인하지 않은 {categories.join(", ")}은(는) 모두 없으신가요?
      </p>
      {showSelect ? (
        <AssetCategorySelectCard availableKeys={categories} onSubmit={onSelectMore} />
      ) : (
        <div className="remaining-categories-actions">
          <Button onClick={onConfirmNone}>네, 모두 없어요</Button>
          <Button variant="outline" onClick={() => setShowSelect(true)}>
            더 있어요
          </Button>
        </div>
      )}
    </Card>
  );
}
