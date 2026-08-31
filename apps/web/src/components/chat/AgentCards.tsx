import type { ReactElement } from "react";
import { useApp } from "../../lib/appState";
import {
  parsePendingQuestions,
  parseShares,
  parseSignals,
  parseTaxResult,
} from "../../lib/agentData";
import { Markdown } from "../../lib/markdown";
import type { AgentOutput } from "../../types";
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
  const { send } = useApp();
  const data = contribution.data ?? {};

  const signals = parseSignals(data, contribution.agent);
  const pending = parsePendingQuestions(data, contribution.agent);
  const tax = parseTaxResult(data, contribution.agent);
  const shares = parseShares(data, contribution.agent);

  const cards: ReactElement[] = [];

  if (mode === "questions") {
    if (pending) {
      pending.forEach((q, i) => {
        cards.push(
          <div key={`pending-${i}`} className="followup-q">
            <div className="pending-q">
              <Markdown>{q.question}</Markdown>
            </div>
            <ChoiceGroup
              ariaLabel={q.question}
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
      <ResultCard key="shares" title="법정상속분 · 유류분">
        <table className="share-table">
          <thead>
            <tr>
              <th>상속인</th>
              <th>법정상속분</th>
              {shares.some((s) => s.forced) && <th>유류분</th>}
            </tr>
          </thead>
          <tbody>
            {shares.map((s) => (
              <tr key={s.heir}>
                <td>{s.heir}</td>
                <td>{s.statutory}</td>
                {shares.some((x) => x.forced) && <td>{s.forced ?? "—"}</td>}
              </tr>
            ))}
          </tbody>
        </table>
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
