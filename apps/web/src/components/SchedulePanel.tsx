import { useApp } from "../lib/appState";
import { Timeline } from "./ui";

/**
 * 우측 일정·체크리스트 패널.
 * heir_navigator 가 만든 절차 계획(plan)이 있을 때만 셸이 이 열을 띄운다.
 * 대화 흐름과 분리해, 해야 할 일과 기한을 한눈에 보고 체크할 수 있게 한다.
 */
export function SchedulePanel() {
  const { plan, planChecks, togglePlanCheck } = useApp();

  if (!plan) return null;

  const total = plan.steps.length;
  const done = plan.steps.filter(
    (s) => planChecks[s.id] ?? s.done ?? false,
  ).length;

  return (
    <aside className="schedule-panel" aria-label="일정 및 체크리스트">
      <div className="schedule-panel-head">
        <h2>체크리스트 · 일정</h2>
        {total > 0 && (
          <span className="schedule-panel-count">
            {done}/{total} 완료
          </span>
        )}
      </div>
      <p className="schedule-panel-lede">
        담당 에이전트가 정리한 절차입니다. 끝낸 항목을 체크하며 진행하세요.
      </p>
      <Timeline plan={plan} checked={planChecks} onToggle={togglePlanCheck} />
    </aside>
  );
}
