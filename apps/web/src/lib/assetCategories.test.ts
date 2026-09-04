import { describe, expect, it } from "vitest";
import {
  ASSET_CATEGORY_OPTIONS,
  TRACKED_ASSET_CATEGORY_KEYS,
  composeCategorySelectionMessage,
  labelFor,
} from "./assetCategories";

describe("composeCategorySelectionMessage", () => {
  it("선택 순서와 무관하게 항상 ASSET_CATEGORY_OPTIONS 순서(자산 먼저, 부채 마지막)로 나열한다", () => {
    // 클릭 순서: 부채 → 예금 → 부동산 (역순으로 선택해도)
    expect(composeCategorySelectionMessage(["부채", "예금", "부동산"])).toBe(
      "예금·적금, 부동산, 대출·기타 부채을(를) 정리할게요.",
    );
  });

  it("단일 선택도 정상 조합된다", () => {
    expect(composeCategorySelectionMessage(["주식"])).toBe(
      "주식을(를) 정리할게요.",
    );
  });

  it("기타는 문장에서 제외한다(백엔드 키워드가 없음)", () => {
    expect(composeCategorySelectionMessage(["주식", "기타"])).toBe(
      "주식을(를) 정리할게요.",
    );
  });

  it("기타만 선택하면 빈 문자열 — 호출부가 이 경우를 특별 처리해야 한다", () => {
    expect(composeCategorySelectionMessage(["기타"])).toBe("");
  });

  it("아무것도 선택 안 하면 빈 문자열", () => {
    expect(composeCategorySelectionMessage([])).toBe("");
  });

  it("보험이 포함돼도 다른 자산과 동일하게 나열된다(백엔드가 즉시 확정 처리)", () => {
    expect(composeCategorySelectionMessage(["주식", "보험"])).toBe(
      "주식, 보험을(를) 정리할게요.",
    );
  });
});

describe("labelFor / TRACKED_ASSET_CATEGORY_KEYS", () => {
  it("등록된 키는 라벨을 돌려주고, 모르는 키는 그대로 돌려준다", () => {
    expect(labelFor("예금")).toBe("예금·적금");
    expect(labelFor("부채")).toBe("대출·기타 부채");
    expect(labelFor("알수없음")).toBe("알수없음");
  });

  it("TRACKED_ASSET_CATEGORY_KEYS는 기타를 제외한 8개 카테고리다", () => {
    expect(TRACKED_ASSET_CATEGORY_KEYS).not.toContain("기타");
    expect(TRACKED_ASSET_CATEGORY_KEYS).toHaveLength(
      ASSET_CATEGORY_OPTIONS.length - 1,
    );
  });
});
