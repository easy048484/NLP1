import type { AgentPlan, PlanStep } from "../../types";
import { downloadText, formatDateKo, daysUntil } from "../../lib/format";

/**
 * heir_navigator 의 "나의 할 일" 타임라인.
 * - 항목별 체크박스(로컬 완료 표시)
 * - 공식 처리기간 배지
 * - .ics 다운로드 (이미 백엔드가 생성)
 */
export function Timeline({
  plan,
  checked,
  onToggle,
}: {
  plan: AgentPlan;
  checked: Record<string, boolean>;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="timeline">
      {plan.deadlines.length > 0 && (
        <ul className="timeline-deadlines">
          {plan.deadlines.map((d) => {
            const left = daysUntil(d.due_date);
            return (
              <li key={d.label}>
                <span className="timeline-deadline-label">{d.label}</span>
                <span className="timeline-deadline-date">
                  {formatDateKo(d.due_date)}
                  {left !== null && (
                    <span className={`timeline-daysleft${left < 0 ? " overdue" : ""}`}>
                      {left < 0 ? `${-left}일 지남` : `D-${left}`}
                    </span>
                  )}
                </span>
                {d.basis && <span className="timeline-deadline-basis">{d.basis}</span>}
              </li>
            );
          })}
        </ul>
      )}

      <ol className="timeline-steps">
        {plan.steps.map((step) => (
          <TimelineStep
            key={step.id}
            step={step}
            checked={checked[step.id] ?? step.done ?? false}
            onToggle={() => onToggle(step.id)}
          />
        ))}
      </ol>

      {plan.calendar_ics && (
        <button
          type="button"
          className="btn btn-outline timeline-ics"
          onClick={() => downloadText("eznext-일정.ics", plan.calendar_ics!)}
        >
          일정 내려받기 (.ics)
        </button>
      )}
    </div>
  );
}

function TimelineStep({
  step,
  checked,
  onToggle,
}: {
  step: PlanStep;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <li className={`timeline-step${checked ? " done" : ""}`}>
      <label className="timeline-step-check">
        <input type="checkbox" checked={checked} onChange={onToggle} />
        <span className="timeline-step-body">
          <span className="timeline-step-title">
            {step.day_offset != null && (
              <span className="timeline-step-day">{step.day_offset}일차</span>
            )}
            {step.title}
          </span>
          {step.detail && <span className="timeline-step-detail">{step.detail}</span>}
          {step.official_period && (
            <span className="timeline-step-period">공식 처리기간 {step.official_period}</span>
          )}
        </span>
      </label>
    </li>
  );
}
