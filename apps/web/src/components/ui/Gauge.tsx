/** 준비도 / 은퇴갭 진행 바. percent 0–100. tone으로 네이비 카드 위(inverse) 대응. */
export function Gauge({
  percent,
  label,
  valueText,
  tone = "default",
}: {
  percent: number;
  label?: string;
  valueText?: string;
  tone?: "default" | "inverse";
}) {
  const clamped = Math.max(0, Math.min(100, Math.round(percent)));
  return (
    <div className={`gauge gauge-${tone}`}>
      {(label || valueText) && (
        <div className="gauge-head">
          {label && <span className="gauge-label">{label}</span>}
          {valueText && <span className="gauge-value">{valueText}</span>}
        </div>
      )}
      <div
        className="gauge-track"
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? "진행도"}
      >
        <span className="gauge-fill" style={{ width: `${clamped}%` }} />
      </div>
    </div>
  );
}
