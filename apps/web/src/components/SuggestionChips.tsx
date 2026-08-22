interface Suggestion {
  label: string;
  message: string;
}

/**
 * orchestrator/router.py 의 _KEYWORD_ROUTES 와 맞춘 예시 질문들입니다.
 * "유언"/"자산정리" -> decedent_estate, "상속세"/"세금" -> tax_calculator,
 * 그 외(또는 이어지는 대화)는 heir_navigator가 기본으로 응답합니다.
 */
const SUGGESTIONS: Suggestion[] = [
  { label: "상속 절차가 궁금해요", message: "상속 절차가 궁금해요" },
  { label: "유언장을 점검하고 싶어요", message: "유언장 검토를 도와주세요" },
  { label: "상속세가 얼마나 나올까요?", message: "상속세가 얼마나 나올지 계산해줘" },
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
