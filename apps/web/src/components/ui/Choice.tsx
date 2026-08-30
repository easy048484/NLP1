import type { ReactNode } from "react";

/**
 * 48px+ 선택 버튼 한 줄/그리드. 자유 입력 대신 값을 확정한다.
 * - 가족 인테이크의 예/아니오, 자녀 수
 * - tax 위저드의 금액 칩
 * - decedent_estate 의 pending_questions 옵션
 *
 * 시니어 UX: 라벨은 의문형이 아니라 선택지 그 자체. 버튼임이 분명하게.
 */
export interface ChoiceOption<T = string> {
  label: string;
  value: T;
  hint?: string;
}

export function ChoiceGroup<T = string>({
  options,
  value,
  onSelect,
  disabled,
  columns = "auto",
  ariaLabel,
}: {
  options: ChoiceOption<T>[];
  value?: T | null;
  onSelect: (value: T) => void;
  disabled?: boolean;
  columns?: "auto" | 2 | 3;
  ariaLabel?: string;
}) {
  return (
    <div
      className={`choice-group choice-cols-${columns}`}
      role="group"
      aria-label={ariaLabel}
    >
      {options.map((opt) => (
        <button
          key={String(opt.value)}
          type="button"
          className={`choice-btn${value === opt.value ? " choice-on" : ""}`}
          aria-pressed={value === opt.value}
          disabled={disabled}
          onClick={() => onSelect(opt.value)}
        >
          <span className="choice-btn-label">{opt.label}</span>
          {opt.hint && <span className="choice-btn-hint">{opt.hint}</span>}
        </button>
      ))}
    </div>
  );
}

export function YesNo({
  onSelect,
  value,
  disabled,
  yesLabel = "네",
  noLabel = "아니요",
}: {
  onSelect: (v: boolean) => void;
  value?: boolean | null;
  disabled?: boolean;
  yesLabel?: string;
  noLabel?: string;
}) {
  return (
    <ChoiceGroup<boolean>
      options={[
        { label: yesLabel, value: true },
        { label: noLabel, value: false },
      ]}
      value={value ?? undefined}
      onSelect={onSelect}
      disabled={disabled}
    />
  );
}

/** 인라인 라벨 + 자식 (질문 카드 안에서 선택지를 감싸는 용도). */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="field-block">
      <span className="field-label">{label}</span>
      {children}
    </div>
  );
}
