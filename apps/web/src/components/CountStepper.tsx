/**
 * 숫자를 버튼 목록에서 고르는 입력(자유 텍스트 대신). family_graph
 * 인테이크의 "자녀는 몇 분이신가요?" 같은 질문에 씁니다. 진짜 +/- 스테퍼
 * 대신 버튼 한 줄로 구현해 오탈자·자연어 파싱 부담 없이 값을 확정할 수
 * 있게 했습니다.
 */
export function CountStepper({
  options,
  onSelect,
  disabled,
  formatLabel,
}: {
  options: number[];
  onSelect: (value: number) => void;
  disabled?: boolean;
  formatLabel?: (value: number) => string;
}) {
  return (
    <div className="intake-choice-row">
      {options.map((n) => (
        <button
          key={n}
          type="button"
          className="intake-choice-btn"
          onClick={() => onSelect(n)}
          disabled={disabled}
        >
          {formatLabel ? formatLabel(n) : `${n}명`}
        </button>
      ))}
    </div>
  );
}
