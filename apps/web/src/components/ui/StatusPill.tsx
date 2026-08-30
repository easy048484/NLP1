/**
 * 준비도 항목 상태. 색 + 텍스트 병기(색만으로 구분 금지).
 * kind → tokens.css의 상태색으로 매핑.
 */
export type StatusKind = "done" | "wip" | "todo" | "attention";

const KIND_ICON: Record<StatusKind, string> = {
  done: "●",
  wip: "◐",
  todo: "○",
  attention: "!",
};

export function StatusPill({ kind, label }: { kind: StatusKind; label: string }) {
  return (
    <span className={`status-pill status-pill-${kind}`}>
      <span aria-hidden="true" className="status-pill-dot">
        {KIND_ICON[kind]}
      </span>
      {label}
    </span>
  );
}
