import type { ReactNode } from "react";

export function Card({
  children,
  className = "",
  as: Tag = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "article";
}) {
  return <Tag className={`card ${className}`}>{children}</Tag>;
}

/**
 * 대화 응답 안에 들어가는 "근거 카드". 골드 좌측보더 + 제목.
 * 숫자·판정은 본문이 아니라 이 카드에 고정한다 (compose 규칙).
 */
export function ResultCard({
  title,
  meta,
  children,
  accentVar = "--brand-gold",
}: {
  title: string;
  meta?: ReactNode;
  children: ReactNode;
  /** 좌측보더 색 CSS 변수 (에이전트별로 바꿀 수 있음) */
  accentVar?: string;
}) {
  return (
    <div className="result-card" style={{ borderLeftColor: `var(${accentVar})` }}>
      <h4 className="result-card-title">{title}</h4>
      <div className="result-card-body">{children}</div>
      {meta && <div className="result-card-meta">{meta}</div>}
    </div>
  );
}
