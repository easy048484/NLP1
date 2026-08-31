/** N단계 진행 표시 (얇은 바). 사후 축에서 독촉으로 읽히지 않게 라벨은 담백하게. */
export function Stepper({
  steps,
  current,
}: {
  steps: string[];
  current: number;
}) {
  const clamped = Math.max(0, Math.min(current, steps.length - 1));
  return (
    <div className="stepper" role="group" aria-label={`${steps.length}단계 중 ${clamped + 1}단계`}>
      <div className="stepper-bars" aria-hidden="true">
        {steps.map((label, i) => (
          <span key={label} className={`stepper-bar${i <= clamped ? " on" : ""}`} />
        ))}
      </div>
      <div className="stepper-label">
        {clamped + 1} / {steps.length} · {steps[clamped]}
      </div>
    </div>
  );
}
