import { describe, expect, it } from "vitest";
import {
  EMPTY_UNIT_TEXT,
  composeAmount,
  decomposeAmount,
  sanitizeUnitDigits,
} from "./amountInput";

describe("composeAmount — 단위 필드 → 원 단위 합산", () => {
  it("3/5/2/0/0 → 352,000,000 (억/천만/백만/십만/만)", () => {
    const amount = composeAmount({
      eok: "3",
      cheonman: "5",
      baekman: "2",
      sipman: "0",
      man: "0",
    });
    expect(amount).toBe(352_000_000);
  });

  it("빈 필드는 0으로 취급한다", () => {
    expect(composeAmount(EMPTY_UNIT_TEXT)).toBe(0);
  });

  it("한 자리를 넘는 값도 그대로 곱해진다(12억)", () => {
    expect(
      composeAmount({ ...EMPTY_UNIT_TEXT, eok: "12" }),
    ).toBe(1_200_000_000);
  });

  it("잔여값(만원 미만 끝수)을 그대로 더한다", () => {
    expect(composeAmount(EMPTY_UNIT_TEXT, 3_456)).toBe(3_456);
  });
});

describe("decomposeAmount — 원 단위 → 단위 필드", () => {
  it("352,000,000 → eok=3, cheonman=5, baekman=2, 나머지 빈 값", () => {
    const { unitText, remainder } = decomposeAmount(352_000_000);
    expect(unitText).toEqual({
      eok: "3",
      cheonman: "5",
      baekman: "2",
      sipman: "",
      man: "",
    });
    expect(remainder).toBe(0);
  });

  it("만원 미만 끝수는 remainder로 분리 보존한다", () => {
    const { unitText, remainder } = decomposeAmount(352_003_456);
    expect(unitText.man).toBe("");
    expect(remainder).toBe(3_456);
  });

  it("compose(decompose(x)) 는 x로 되돌아온다(만원 단위 정렬 값)", () => {
    const original = 250_000_000; // +1억 x2 + +5천만
    const { unitText, remainder } = decomposeAmount(original);
    expect(composeAmount(unitText, remainder)).toBe(original);
  });

  it("0은 모든 필드가 빈 문자열이다", () => {
    const { unitText, remainder } = decomposeAmount(0);
    expect(unitText).toEqual(EMPTY_UNIT_TEXT);
    expect(remainder).toBe(0);
  });
});

describe("sanitizeUnitDigits", () => {
  it("숫자 이외 문자를 제거한다", () => {
    expect(sanitizeUnitDigits("1a2b3")).toBe("123");
    expect(sanitizeUnitDigits("")).toBe("");
  });
});

describe("빠른 추가 누적 시나리오", () => {
  it("+1억 x2 + +5천만 = 250,000,000", () => {
    let total = 0;
    total += 100_000_000;
    total += 100_000_000;
    total += 50_000_000;
    expect(total).toBe(250_000_000);
    const { unitText, remainder } = decomposeAmount(total);
    expect(composeAmount(unitText, remainder)).toBe(250_000_000);
  });
});
