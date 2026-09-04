/**
 * asset_organizer 금액 입력 위젯(AmountInputCard)의 순수 계산 로직.
 *
 * 억/천만/백만/십만/만 단위 필드 ↔ 원 단위 정수 상호 변환, 빠른 추가 누적을
 * 담당한다. React state와 분리해 jsdom 없이도(vitest environment: node)
 * 단위 테스트할 수 있게 한다.
 */

export const AMOUNT_UNIT_FIELDS = [
  { key: "eok", label: "억", multiplier: 100_000_000 },
  { key: "cheonman", label: "천만", multiplier: 10_000_000 },
  { key: "baekman", label: "백만", multiplier: 1_000_000 },
  { key: "sipman", label: "십만", multiplier: 100_000 },
  { key: "man", label: "만", multiplier: 10_000 },
] as const;

export type AmountUnitKey = (typeof AMOUNT_UNIT_FIELDS)[number]["key"];
export type AmountUnitText = Record<AmountUnitKey, string>;

export const EMPTY_UNIT_TEXT: AmountUnitText = {
  eok: "",
  cheonman: "",
  baekman: "",
  sipman: "",
  man: "",
};

export const QUICK_ADD_OPTIONS: { label: string; value: number }[] = [
  { label: "+5억", value: 500_000_000 },
  { label: "+1억", value: 100_000_000 },
  { label: "+5천만", value: 50_000_000 },
  { label: "+1천만", value: 10_000_000 },
  { label: "+500만", value: 5_000_000 },
  { label: "+100만", value: 1_000_000 },
  { label: "+10만", value: 100_000 },
];

/** 단위 필드 입력에서 숫자 이외 문자를 제거한다(붙여넣기 등 대비). */
export function sanitizeUnitDigits(raw: string): string {
  return raw.replace(/[^0-9]/g, "");
}

/**
 * 원 단위 정수를 단위 필드(값이 0이면 빈 문자열로 표시)와 만원 미만
 * 잔여값으로 분해한다. 잔여값은 단위 필드로 표현할 수 없는 정밀도를
 * 보존해 두었다가 재조합(composeAmount) 시 그대로 되돌려준다 — 직접
 * 입력으로 만원 미만 끝수가 있는 금액을 넣은 뒤 단위 필드 쪽으로
 * 전환해도 끝수가 조용히 사라지지 않는다.
 */
export function decomposeAmount(amount: number): {
  unitText: AmountUnitText;
  remainder: number;
} {
  let rest = Math.max(0, Math.round(amount));
  const unitText = { ...EMPTY_UNIT_TEXT };
  for (const field of AMOUNT_UNIT_FIELDS) {
    const n = Math.floor(rest / field.multiplier);
    unitText[field.key] = n > 0 ? String(n) : "";
    rest -= n * field.multiplier;
  }
  return { unitText, remainder: rest };
}

/**
 * 단위 필드 + 만원 미만 잔여값을 원 단위 정수로 합산한다. 빈 값·음수·비숫자는
 * 0으로 취급한다(입력 도중 상태이므로 여기서 실패시키지 않는다 — 확정 여부는
 * 호출부의 별도 "touched" 상태로 판단한다).
 */
export function composeAmount(unitText: AmountUnitText, remainder = 0): number {
  let total = Math.max(0, Math.round(remainder));
  for (const field of AMOUNT_UNIT_FIELDS) {
    const raw = unitText[field.key];
    const n = raw ? Number(sanitizeUnitDigits(raw)) : 0;
    if (Number.isFinite(n) && n > 0) total += n * field.multiplier;
  }
  return total;
}
