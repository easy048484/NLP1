import type { ReactElement } from "react";
import { useApp } from "../../lib/appState";
import {
  hasCategorySelectionRequest,
  parseAssetAmountRequest,
  parseAssetReview,
  parsePendingQuestions,
  parseRemainingCategoriesPrompt,
  parseShares,
  parseShareWarnings,
  parseSignals,
  parseTaxResult,
  type AssetReviewItem,
} from "../../lib/agentData";
import { composeCategorySelectionMessage } from "../../lib/assetCategories";
import { Markdown } from "../../lib/markdown";
import { formatWonExact } from "../../lib/format";
import type { AgentOutput } from "../../types";
import { AmountInputCard } from "./AmountInputCard";
import { AssetCategorySelectCard } from "./AssetCategorySelectCard";
import { AssetReviewCard } from "./AssetReviewCard";
import { RemainingCategoriesPrompt } from "./RemainingCategoriesPrompt";
import {
  AmountDisplay,
  ChoiceGroup,
  ResultCard,
  SignalRow,
  TaxBreakdown,
} from "../ui";

/**
 * 한 기여(contribution)의 agent + data 를 알맞은 근거 카드로 렌더한다.
 * 숫자·판정은 항상 여기(카드)에 고정하고, 본문 마크다운엔 서술만 남긴다.
 *
 * mode="results"  — 안내·근거 카드만 (후속 질문 제외)
 * mode="questions" — 후속 질문(선택지)만
 * 절차 타임라인(plan)은 우측 SchedulePanel 로 분리했으므로 여기서 렌더하지 않는다.
 */
export function AgentCards({
  contribution,
  mode = "results",
}: {
  contribution: AgentOutput;
  mode?: "results" | "questions";
}) {
  const { send, loading } = useApp();
  const data = contribution.data ?? {};

  const signals = parseSignals(data, contribution.agent);
  const amountRequest = parseAssetAmountRequest(data, contribution.agent);
  const review = parseAssetReview(data, contribution.agent);
  const categorySelectionRequested = hasCategorySelectionRequest(data, contribution.agent);
  const remainingCategories = parseRemainingCategoriesPrompt(data, contribution.agent);
  const pending = parsePendingQuestions(data, contribution.agent);
  const tax = parseTaxResult(data, contribution.agent);
  const shares = parseShares(data, contribution.agent);
  const shareWarnings = parseShareWarnings(data, contribution.agent);

  const cards: ReactElement[] = [];

  // 카테고리 선택("자산 정리하고 싶어요" 시작 의사, 또는 남은 카테고리
  // 중 "더 있어요")에서 선택 완료를 누르면 실제 파싱은 백엔드
  // extractor.py의 기존 키워드 매칭 경로를 그대로 탄다 — 선택한 라벨을
  // 나열한 평문 문장을 보낼 뿐, 별도 구조화 context는 쓰지 않는다
  // (composeCategorySelectionMessage 문서 참고). "기타"만 선택하면 대응
  // 키워드가 없어 빈 문자열이 되므로, 그 경우에만 자유 입력을 유도하는
  // 문장으로 대신한다.
  const submitCategorySelection = (selectedKeys: string[]) => {
    const message = composeCategorySelectionMessage(selectedKeys);
    void send(message || "기타 자산이 있어요.");
  };

  if (mode === "questions") {
    // pending_amounts(특정 카테고리 금액 되묻기)와 pending_categories(전체
    // 카테고리 나열)는 백엔드에서 항상 서로 배타적이다
    // (agent.py._continue_after_categories) — 금액 되묻기가 있으면 그쪽을
    // 우선하고, 긴 원 단위 숫자를 직접 치지 않아도 되는 단위 입력 위젯을
    // 보여준다.
    if (amountRequest) {
      cards.push(
        <AmountInputCard
          key="amount-input"
          label={amountRequest.label}
          onConfirm={(amountWon) => void send(`${amountWon}원`)}
          onUnknown={() => void send("몰라요")}
          disabled={loading}
        />,
      );
      return <div className="agent-cards">{cards}</div>;
    }
    // 수집이 끝나면(status==="reviewing") 곧바로 finalized로 넘어가지
    // 않고 이 화면에서 항목별 확인/수정을 거친다. [수정]은 항목의
    // target(구조화 식별자)을 그대로 context.edit_target으로 보내고,
    // [이대로 확정]은 context.confirm_review로만 판단한다 — 둘 다
    // 텍스트 추론에 의존하지 않는다(agent.py._build_review_items 참고).
    if (review) {
      const handleEdit = (item: AssetReviewItem) => {
        void send(`${item.label} 수정할게요`, {
          context: { edit_target: item.target },
        });
      };
      const handleConfirm = () => {
        void send("이대로 확정할게요", { context: { confirm_review: true } });
      };
      cards.push(
        <AssetReviewCard
          key="asset-review"
          items={review.items}
          onEdit={handleEdit}
          onConfirm={handleConfirm}
          disabled={loading}
        />,
      );
      return <div className="agent-cards">{cards}</div>;
    }
    // 시작 의사만 있고 구체적 항목이 없을 때(awaiting_category_selection)
    // — 파싱 실패 재질문 대신 카테고리 선택 UI로 바로 진입시킨다.
    if (categorySelectionRequested) {
      cards.push(
        <AssetCategorySelectCard
          key="category-select"
          onSubmit={submitCategorySelection}
          disabled={loading}
        />,
      );
      return <div className="agent-cards">{cards}</div>;
    }
    // 선택한 카테고리 입력이 끝난 뒤 남은 미확인 카테고리 일괄 확인 —
    // "네, 모두 없어요"(기존 평문 부정 답변 경로)와 "더 있어요"(같은
    // 선택 UI를 남은 카테고리로 좁혀 재표시) 두 갈래.
    if (remainingCategories) {
      cards.push(
        <RemainingCategoriesPrompt
          key="remaining-categories"
          categories={remainingCategories.categories}
          onConfirmNone={() => void send("나머지는 없어요")}
          onSelectMore={submitCategorySelection}
          disabled={loading}
        />,
      );
      return <div className="agent-cards">{cards}</div>;
    }
    if (pending) {
      pending.forEach((q, i) => {
        cards.push(
          <div key={`pending-${i}`} className="followup-q">
            <div className="pending-q">
              <Markdown>{q.question}</Markdown>
            </div>
            <ChoiceGroup
              ariaLabel={q.question}
              disabled={loading}
              options={q.options}
              onSelect={(value) => {
                const chosen = q.options.find((o) => o.value === value);
                // 선택지는 텍스트가 아니라 구조화 답변으로 보낸다 — 백엔드 에이전트가
                // context[field] 로 읽는다 (예: decedent_estate 의 will_type).
                void send(
                  chosen?.label ?? value,
                  q.field ? { context: { [q.field]: value } } : undefined,
                );
              }}
            />
          </div>,
        );
      });
    }
    if (cards.length === 0) return null;
    return <div className="agent-cards">{cards}</div>;
  }

  if (shares) {
    cards.push(
      <ResultCard
        key="shares"
        title="법정상속분 · 유류분"
        meta="참고용 1차 시뮬레이션입니다. 단순 부족액은 실제 청구 가능 여부나 최종 반환금액을 뜻하지 않으며 전문가 검토가 필요합니다."
      >
        <div style={{ overflowX: "auto" }}>
          <table className="share-table">
            <thead>
              <tr>
                <th>상속인</th>
                <th>법정상속분</th>
                {shares.some((s) => s.forced) && <th>기본 유류분 예상액</th>}
                <th>예정 취득액</th>
                <th>단순 부족액</th>
              </tr>
            </thead>
            <tbody>
              {shares.map((s, i) => (
                <tr key={`${s.heir}-${i}`}>
                  <td>{s.heir}</td>
                  <td>{s.statutory}</td>
                  {shares.some((x) => x.forced) && <td>{s.forced ?? "—"}</td>}
                  <td>
                    {s.planned_acquisition == null
                      ? "미확인"
                      : formatWonExact(s.planned_acquisition)}
                  </td>
                  <td>
                    {s.simple_gap == null ? "비교 전" : formatWonExact(s.simple_gap)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {shareWarnings.length > 0 && (
          <ul>
            {shareWarnings.map((warning, i) => <li key={i}>{warning}</li>)}
          </ul>
        )}
      </ResultCard>,
    );
  }

  if (signals) {
    cards.push(
      <ResultCard
        key="signals"
        title="유언 요건 점검"
        meta="색은 판례 상태를 나타냅니다. 유효·무효를 단정하지 않습니다."
      >
        <div className="signal-list">
          {signals.map((s) => (
            <SignalRow key={s.id} signal={s} />
          ))}
        </div>
      </ResultCard>,
    );
  }

  if (tax) {
    cards.push(
      <ResultCard key="tax" title="상속세 시산">
        <TaxBreakdown result={tax} />
        {tax.final_amount != null && (
          <AmountDisplay
            label="최종 예상 상속세"
            amount={tax.final_amount}
            note="배우자 공제·금융재산 공제를 반영한 시산이며, 실제 신고세액이 아닙니다."
          />
        )}
      </ResultCard>,
    );
  }

  if (cards.length === 0) return null;
  return <div className="agent-cards">{cards}</div>;
}
