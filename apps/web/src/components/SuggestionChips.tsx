interface Suggestion {
  label: string;
  message: string;
}

/**
 * 각 에이전트 apps/api/agents/<이름>/spec.py 의 keywords 와 맞춘 예시 질문들입니다.
 * "유언" -> decedent_estate, "상속세" -> tax_calculator, "절차" -> heir_navigator.
 * 마지막 칩은 키워드가 두 에이전트에 걸려 Full Pipeline(병렬 실행 + 합성)을 타는
 * 데모 케이스입니다 (docs/라우팅방식변경.md 시나리오 B).
 */
const SUGGESTIONS: Suggestion[] = [
  { label: "상속 절차가 궁금해요", message: "상속 절차가 궁금해요" },
  { label: "유언장을 점검하고 싶어요", message: "유언장 검토를 도와주세요" },
  { label: "상속세가 얼마나 나올까요?", message: "상속세가 얼마나 나올지 계산해줘" },
  {
    label: "은퇴 준비 + 상속세",
    message: "은퇴 준비하면서 상속세도 궁금해요",
  },
];

export function SuggestionChips({
  onPick,
  disabled,
}: {
  onPick: (message: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="suggestion-row">
      {SUGGESTIONS.map((s) => (
        <button
          key={s.label}
          type="button"
          className="suggestion-chip"
          onClick={() => onPick(s.message)}
          disabled={disabled}
        >
          {s.label}
        </button>
      ))}
    </div>
  );
}
