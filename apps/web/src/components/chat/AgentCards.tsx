import type { ReactElement } from "react";
import { useApp } from "../../lib/appState";
import {
  parsePendingQuestions,
  parsePlan,
  parseShares,
  parseSignals,
  parseTaxResult,
} from "../../lib/agentData";
import type { AgentOutput, AgentPlan } from "../../types";
import {
  AmountDisplay,
  ChoiceGroup,
  ResultCard,
  SignalRow,
  TaxBreakdown,
  Timeline,
} from "../ui";

/**
 * 한 기여(contribution)의 agent + data 를 알맞은 근거 카드로 렌더한다.
 * 숫자·판정은 항상 여기(카드)에 고정하고, 본문 마크다운엔 서술만 남긴다.
 */
export function AgentCards({
  contribution,
  topLevelPlan,
}: {
  contribution: AgentOutput;
  topLevelPlan?: AgentPlan | null;
}) {
  const { planChecks, togglePlanCheck, send } = useApp();
  const data = contribution.data ?? {};

  const plan = topLevelPlan ?? parsePlan(data);
  const signals = parseSignals(data);
  const pending = parsePendingQuestions(data);
  const tax = parseTaxResult(data);
  const shares = parseShares(data);

  const cards: ReactElement[] = [];

  if (contribution.agent === "heir_navigator" && plan) {
    cards.push(
      <ResultCard key="plan" title="나의 할 일">
        <Timeline plan={plan} checked={planChecks} onToggle={togglePlanCheck} />
      </ResultCard>,
    );
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

  if (pending) {
    pending.forEach((q, i) => {
      cards.push(
        <ResultCard key={`pending-${i}`} title="직접 확인해 주세요">
          <p className="pending-q">{q.question}</p>
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
        </ResultCard>,
      );
    });
  }

  if (cards.length === 0) return null;
  return <div className="agent-cards">{cards}</div>;
}
