import { useNavigate } from "react-router-dom";
import { useApp } from "../lib/appState";
import { buildPrep, prepPercent } from "../lib/prep";
import { RELATION_LABELS } from "../lib/relations";
import { formatWon } from "../lib/format";
import { Gauge, StatusPill } from "./ui";

/**
 * 우측 상시 컨텍스트 패널.
 * ① 가족관계 요약(+수정) ② 준비도 카드 ③ 현재 단계 ④ financial_profile 요약
 */
export function ContextPanel({ onEditFamily }: { onEditFamily: () => void }) {
  const { axis, familyGraph, plan, planChecks, financialProfile } = useApp();
  const navigate = useNavigate();

  const prep = buildPrep({ axis, familyGraph, plan, planChecks, financialProfile });
  const percent = prepPercent(prep);
  const members = familyGraph?.members ?? [];

  return (
    <aside className="context-panel" aria-label="준비 현황">
      <section className="ctx-ledger">
        <div className="ctx-ledger-hello">나의 준비 현황</div>
        <Gauge
          tone="inverse"
          label="준비도"
          valueText={`${percent}%`}
          percent={percent}
        />
      </section>

      <section className="ctx-block">
        <div className="ctx-block-head">
          <h3>가족관계</h3>
          <button type="button" className="ctx-link" onClick={onEditFamily}>
            수정
          </button>
        </div>
        {members.length === 0 ? (
          <p className="ctx-empty">
            아직 등록 전이에요.{" "}
            <button
              type="button"
              className="ctx-link"
              onClick={() => navigate("/onboarding/family")}
            >
              지금 등록
            </button>
          </p>
        ) : (
          <ul className="ctx-member-list">
            {members.map((m) => (
              <li key={m.id}>
                <span className="ctx-member-rel">{RELATION_LABELS[m.relation]}</span>
                <span className="ctx-member-name">{m.name}</span>
                {m.is_minor && <span className="ctx-tag">미성년</span>}
                {!m.is_alive && <span className="ctx-tag">사망</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="ctx-block">
        <h3>준비 항목</h3>
        <ul className="ctx-prep-list">
          {prep.map((item) => (
            <li key={item.key}>
              <button
                type="button"
                className="ctx-prep-item"
                onClick={() => navigate(item.route)}
              >
                <span className="ctx-prep-title">{item.title}</span>
                <StatusPill kind={item.status} label={item.statusLabel} />
                <span className="ctx-prep-desc">{item.desc}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      {financialProfile && (
        <section className="ctx-block">
          <h3>자산 요약</h3>
          <ul className="ctx-fin-list">
            {financialProfile.assets.map((a) => (
              <li key={a.label}>
                <span>{a.label}</span>
                <span className="ctx-fin-amount">{formatWon(a.amount)}</span>
              </li>
            ))}
            {financialProfile.retirement_gap != null && (
              <li className="ctx-fin-gap">
                <span>은퇴자금 갭</span>
                <span className="ctx-fin-amount">
                  {formatWon(financialProfile.retirement_gap)}
                </span>
              </li>
            )}
          </ul>
        </section>
      )}
    </aside>
  );
}
