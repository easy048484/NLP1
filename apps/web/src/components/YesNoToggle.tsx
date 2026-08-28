/**
 * 예/아니오 두 버튼 입력. family_graph 인테이크(FamilyIntake)뿐 아니라
 * 팀원별_업무_배정_0823.md 1-2절에서 승원님이 제안한 tax_calculator의
 * "선택형 UI" 전환에도 그대로 재사용할 수 있도록 라벨을 커스터마이즈할
 * 수 있게 만들었습니다.
 */
export function YesNoToggle({
  onSelect,
  disabled,
  yesLabel = "네",
  noLabel = "아니요",
}: {
  onSelect: (value: boolean) => void;
  disabled?: boolean;
  yesLabel?: string;
  noLabel?: string;
}) {
  return (
    <div className="intake-choice-row">
      <button
        type="button"
        className="intake-choice-btn"
        onClick={() => onSelect(true)}
        disabled={disabled}
      >
        {yesLabel}
      </button>
      <button
        type="button"
        className="intake-choice-btn"
        onClick={() => onSelect(false)}
        disabled={disabled}
      >
        {noLabel}
      </button>
    </div>
  );
}
