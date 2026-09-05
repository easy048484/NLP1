import { Button, Card } from "../ui";
import { formatWonExact } from "../../lib/format";
import type { AssetReviewItem } from "../../lib/agentData";

/**
 * asset_organizer 수집이 끝난 뒤(state.status === "reviewing") 보여주는
 * 전체 항목 확인 화면 — 사용자가 [수정]으로 개별 항목을 고치거나 [이대로
 * 확정]으로 finalized까지 넘길 수 있다.
 *
 * [수정] 클릭은 항목의 `target`(백엔드가 만든 구조화 식별자)을 그대로
 * `context.edit_target`에 실어 보낸다 — 라벨 텍스트를 다시 파싱해서
 * 대상을 추측하지 않는다(agent.py._build_review_items 참고). [이대로
 * 확정]도 마찬가지로 `context.confirm_review`만 보고 판단하므로, 버튼의
 * 표시 문구 자체는 백엔드 동작에 영향을 주지 않는다.
 */
export function AssetReviewCard({
  items,
  onEdit,
  onConfirm,
  disabled = false,
}: {
  items: AssetReviewItem[];
  onEdit: (item: AssetReviewItem) => void;
  onConfirm: () => void;
  /** 응답 대기 중(loading) 등 제출 자체를 잠깐 막아야 할 때. */
  disabled?: boolean;
}) {
  return (
    <Card className="asset-review-card">
      <div className="asset-review-list">
        {items.map((item) => (
          <div key={`${item.kind}-${item.label}`} className="asset-review-row">
            <span className="asset-review-label">
              {item.label}
              {item.excludedFromTotals && (
                <span className="asset-review-note"> (합계 제외)</span>
              )}
            </span>
            <span className="asset-review-value">
              {item.confidence === "confirmed" && item.value != null
                ? formatWonExact(item.value)
                : "금액 미확인"}
            </span>
            <Button
              variant="outline"
              onClick={() => onEdit(item)}
              disabled={disabled}
            >
              수정
            </Button>
          </div>
        ))}
      </div>
      <div className="asset-review-actions">
        <Button onClick={onConfirm} disabled={disabled}>
          이대로 확정
        </Button>
      </div>
    </Card>
  );
}
