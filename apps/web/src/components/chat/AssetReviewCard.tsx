import { Button, Card } from "../ui";
import { formatWonExact } from "../../lib/format";
import type { AssetReviewItem } from "../../lib/agentData";

/**
 * asset_organizer 수집이 끝난 뒤(state.status === "reviewing") 보여주는
 * 전체 항목 확인 화면 — [수정]으로 개별 항목을 고치거나 [이대로 확정]으로
 * finalized까지 넘긴다.
 *
 * [수정]은 항목의 `target`(백엔드가 만든 구조화 식별자)을 `context.edit_target`에
 * 그대로 실어 보내며 라벨 텍스트로 대상을 추측하지 않는다(agent.py._build_review_items
 * 참고). [이대로 확정]도 `context.confirm_review`만 보므로 버튼 문구는 백엔드
 * 동작에 영향을 주지 않는다.
 *
 * `excludedFromTotals`(현재는 보험) 행 라벨에는 "(합계 제외)"를 붙이지 않는다
 * — "보험은 재산이 아닌가?"로 오해하기 쉬웠다(실측 피드백). 대신 해당 항목이
 * 있으면 카드 하단에 안내문을 한 번만 보여주며, 세법·법률 판단(과세 대상 여부
 * 등)은 하지 않는다. 표시 문구만의 문제이고 집계 로직은 백엔드에 있다.
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
  const hasExcludedItem = items.some((item) => item.excludedFromTotals);

  return (
    <Card className="asset-review-card">
      <div className="asset-review-list">
        {items.map((item) => (
          <div key={`${item.kind}-${item.label}`} className="asset-review-row">
            <span className="asset-review-label">{item.label}</span>
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
      {hasExcludedItem && (
        <p className="asset-review-exclusion-note">
          보험은 금액의 성격(해약환급금·보험금 등)과 계약 관계에 따라
          다르게 취급될 수 있어 이 화면의 자산 합계에는 자동 반영하지
          않습니다.
        </p>
      )}
      <div className="asset-review-actions">
        <Button onClick={onConfirm} disabled={disabled}>
          이대로 확정
        </Button>
      </div>
    </Card>
  );
}
