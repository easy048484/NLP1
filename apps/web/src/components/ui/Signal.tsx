import { useState } from "react";
import type { PrecedentRef, RequirementSignal, SignalGrade } from "../../types";

/**
 * 유언 요건 신호등. 색 = 판례 상태(우리 의견 아님).
 * 스펙: apps/api/agents/decedent_estate/요건판정_문구_스펙_v1.md §3-2
 * 색만으로 구분 금지 → 아이콘 + 배지 텍스트 항상 병기.
 */
const GRADE_ICON: Record<SignalGrade, string> = {
  green: "✓",
  red: "✕",
  yellow: "⚠",
  gray: "ℹ",
  pending: "?",
};

export function SignalRow({ signal }: { signal: RequirementSignal }) {
  const [showPrecedent, setShowPrecedent] = useState(false);
  const hasPrecedent = (signal.precedents?.length ?? 0) > 0;

  return (
    <div className={`signal-row signal-${signal.grade}`}>
      <div className="signal-row-head">
        <span className="signal-name">
          <span aria-hidden="true" className="signal-icon">
            {GRADE_ICON[signal.grade]}
          </span>
          {signal.name}
        </span>
        <span className="signal-badge">{signal.badge}</span>
      </div>
      <p className="signal-body">{signal.body}</p>
      {hasPrecedent && (
        <>
          <button
            type="button"
            className="signal-why"
            aria-expanded={showPrecedent}
            onClick={() => setShowPrecedent((v) => !v)}
          >
            왜 그런가요? {showPrecedent ? "▲" : "▼"}
          </button>
          {showPrecedent && (
            <div
              className={`precedent-cards${
                (signal.precedents?.length ?? 0) > 1 ? " precedent-cards-two" : ""
              }`}
            >
              {signal.precedents!.map((p) => (
                <PrecedentCard key={p.case_no} precedent={p} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** 판례 카드 — 기본은 SignalRow 안에서 접힘. 단독으로도 사용 가능. */
export function PrecedentCard({ precedent }: { precedent: PrecedentRef }) {
  return (
    <div className="precedent-card">
      <div className="precedent-case">{precedent.case_no}</div>
      <p className="precedent-summary">{precedent.summary}</p>
    </div>
  );
}
