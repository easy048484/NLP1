import { useState } from "react";
import { Button, Card } from "../ui";
import { formatWon, formatWonExact, parseKrw } from "../../lib/format";
import {
  AMOUNT_UNIT_FIELDS,
  EMPTY_UNIT_TEXT,
  QUICK_ADD_OPTIONS,
  composeAmount,
  decomposeAmount,
  sanitizeUnitDigits,
  type AmountUnitKey,
  type AmountUnitText,
} from "../../lib/amountInput";

interface Snapshot {
  /** null = 아직 아무것도 입력 안 함(미입력). 0 이상 정수면 명시적으로 입력한 값. */
  amount: number | null;
  /** 단위 필드로 표현할 수 없는 만원 미만 잔여값(직접 입력 유입분 보존용). */
  remainder: number;
  unitText: AmountUnitText;
}

const EMPTY_SNAPSHOT: Snapshot = { amount: null, remainder: 0, unitText: EMPTY_UNIT_TEXT };

/**
 * asset_organizer가 특정 카테고리(예금/부동산/대출 등)의 금액을 물을 때
 * (state.pending_amounts) 긴 원 단위 숫자를 직접 치지 않고도 답할 수 있게
 * 하는 위젯. 단위별 입력/빠른 추가/직접 입력이 모두 하나의 amount state를
 * 공유하고, 서로 전환해도 값이 동기화된다.
 *
 * 백엔드에는 평문 금액 문자열(예: "352000000원")을 그대로 user_message로
 * 보낸다 — asset_organizer의 pending_amounts 단답 해석 경로
 * (extractor.parse_monthly_expense_answer → _parse_amount)가 이미 이 형식을
 * 지원하므로, 이 위젯 때문에 백엔드 계약을 바꿀 필요가 없다("몰라요"도
 * 마찬가지로 기존 _wants_unknown_amount 인식 경로를 그대로 탄다).
 *
 * 미입력(null) ≠ 0원 ≠ 금액 모름을 명확히 구분한다 — "이 금액으로 답하기"는
 * 사용자가 실제로 뭔가 입력한 뒤(touched)에만 눌린다. 단위 필드가 비어
 * 있으면 미리보기에는 0원처럼 보이지만, 그 상태 그대로는 확정(제출)할 수
 * 없다 — 초기화/빈 입력이 조용히 0원으로 저장되는 걸 막는다.
 */
export function AmountInputCard({
  label,
  onConfirm,
  onUnknown,
}: {
  label: string;
  onConfirm: (amountWon: number) => void;
  onUnknown: () => void;
}) {
  const [snapshot, setSnapshot] = useState<Snapshot>(EMPTY_SNAPSHOT);
  const [history, setHistory] = useState<Snapshot[]>([]);
  const [touched, setTouched] = useState(false);
  const [unknownSelected, setUnknownSelected] = useState(false);
  const [directOpen, setDirectOpen] = useState(false);
  const [directText, setDirectText] = useState("");

  const { remainder, unitText } = snapshot;
  const previewAmount = touched ? snapshot.amount ?? 0 : 0;
  const canSubmit = touched && snapshot.amount != null;

  const applySnapshot = (next: Snapshot) => {
    setHistory((h) => [...h, snapshot]);
    setSnapshot(next);
    setDirectText(next.amount != null ? String(next.amount) : "");
    setTouched(true);
    setUnknownSelected(false);
  };

  const handleUnitChange = (key: AmountUnitKey, raw: string) => {
    const digits = sanitizeUnitDigits(raw).slice(0, 6);
    const nextUnitText = { ...unitText, [key]: digits };
    const nextAmount = composeAmount(nextUnitText, remainder);
    applySnapshot({ amount: nextAmount, remainder, unitText: nextUnitText });
  };

  const handleQuickAdd = (delta: number) => {
    const base = touched ? snapshot.amount ?? 0 : 0;
    const next = base + delta;
    const { unitText: nextUnitText, remainder: nextRemainder } = decomposeAmount(next);
    applySnapshot({ amount: next, remainder: nextRemainder, unitText: nextUnitText });
  };

  const handleDirectChange = (raw: string) => {
    setDirectText(raw);
    const parsed = parseKrw(raw);
    if (parsed == null || parsed < 0) return;
    const { unitText: nextUnitText, remainder: nextRemainder } = decomposeAmount(parsed);
    setHistory((h) => [...h, snapshot]);
    setSnapshot({ amount: parsed, remainder: nextRemainder, unitText: nextUnitText });
    setTouched(true);
    setUnknownSelected(false);
  };

  const handleUndo = () => {
    setHistory((h) => {
      if (h.length === 0) return h;
      const prev = h[h.length - 1];
      setSnapshot(prev);
      setDirectText(prev.amount != null ? String(prev.amount) : "");
      setTouched(prev.amount != null);
      return h.slice(0, -1);
    });
  };

  const handleReset = () => {
    setHistory((h) => [...h, snapshot]);
    setSnapshot(EMPTY_SNAPSHOT);
    setDirectText("");
    setTouched(false);
    setUnknownSelected(false);
  };

  const handleUnknown = () => {
    setUnknownSelected(true);
    onUnknown();
  };

  const handleSubmit = () => {
    if (!canSubmit || snapshot.amount == null) return;
    onConfirm(snapshot.amount);
  };

  return (
    <Card className="amount-input-card">
      <div className="amount-input-head">
        <span className="amount-input-label">{label} 금액</span>
      </div>

      <div className="amount-unit-row">
        {AMOUNT_UNIT_FIELDS.map((field) => (
          <label key={field.key} className="amount-unit-field">
            <span className="amount-unit-name">{field.label}</span>
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              className="amount-unit-input"
              aria-label={`${label} 금액 ${field.label} 단위`}
              placeholder="0"
              value={unitText[field.key]}
              onChange={(e) => handleUnitChange(field.key, e.target.value)}
            />
          </label>
        ))}
      </div>

      <div className="amount-preview" aria-live="polite">
        <div className="amount-preview-ko">{formatWon(previewAmount)}</div>
        <div className="amount-preview-exact">{formatWonExact(previewAmount)}</div>
      </div>

      <div className="amount-quick-adds">
        {QUICK_ADD_OPTIONS.map((q) => (
          <button
            key={q.label}
            type="button"
            className="amount-quick-btn"
            onClick={() => handleQuickAdd(q.value)}
          >
            {q.label}
          </button>
        ))}
      </div>

      <div className="amount-tool-row">
        <Button variant="outline" onClick={handleUndo} disabled={history.length === 0}>
          되돌리기
        </Button>
        <Button variant="outline" onClick={handleReset}>
          초기화
        </Button>
      </div>

      <button
        type="button"
        className="amount-direct-toggle"
        onClick={() => setDirectOpen((v) => !v)}
        aria-expanded={directOpen}
      >
        직접 숫자로 입력하기 {directOpen ? "▲" : "▼"}
      </button>
      {directOpen && (
        <input
          type="text"
          inputMode="numeric"
          className="amount-direct-input"
          placeholder="예: 3억 5,200만원 / 352000000"
          aria-label={`${label} 금액 직접 입력`}
          value={directText}
          onChange={(e) => handleDirectChange(e.target.value)}
        />
      )}

      <div className="amount-input-actions">
        <Button variant="ghost" onClick={handleUnknown}>
          금액을 몰라요
        </Button>
        <Button onClick={handleSubmit} disabled={!canSubmit}>
          이 금액으로 답하기
        </Button>
      </div>

      {unknownSelected && (
        <p className="amount-unknown-note">
          "금액을 몰라요"로 답했어요. 숫자를 입력하면 이 선택은 취소돼요.
        </p>
      )}
    </Card>
  );
}
