import { describe, expect, it } from "vitest";
import { parseSignals } from "./agentData";

/**
 * decedent_estate.requirements는 {id: item} dict다(배열 아님) — 실제 API가
 * 보내는 모양 그대로 구성한다. 예전에는 parseSignals가 이 모양을 배열로만
 * 읽으려 해서 항상 null을 반환했고, "유언 요건 점검" 카드가 한 번도 렌더된
 * 적이 없었다(A안 구현 중 발견). requirements[rid].body/precedents는 그
 * 요건 자신의 것만 담아야 한다(다른 요건 판례가 섞이면 안 됨).
 */
function decedentEstateData() {
  return {
    decedent_estate: {
      will_type: "handwritten",
      requirements: {
        date: {
          id: "date",
          name: "연월일",
          grade: "GREEN",
          condition_id: "all_present",
          red_label: null,
          precedent_ids: [],
          body: "✅ 연월일: 기재 확인 (2026년 5월 3일)",
          precedents: [],
          extracted: {},
          followup_question: null,
        },
        address: {
          id: "address",
          name: "주소",
          grade: "RED",
          condition_id: "absent",
          red_label: "유언자 주소",
          precedent_ids: ["address_missing_invalid"],
          body: "❌ 주소: 유언자 주소가 확인되지 않습니다",
          precedents: [
            { case_no: "2012다71688", summary: "주소 누락 관련 판시 요지" },
          ],
          extracted: {},
          followup_question: null,
        },
        interseal: {
          id: "interseal",
          name: "간인",
          grade: null,
          condition_id: "single_page",
          red_label: null,
          precedent_ids: [],
          body: "",
          precedents: [],
          extracted: {},
          followup_question: null,
        },
      },
      pending_questions: [],
      progress: { checked: 2, total: 5 },
    },
  };
}

describe("parseSignals", () => {
  it("requirements가 dict여도 배열로 변환해 파싱한다", () => {
    const signals = parseSignals(decedentEstateData());
    expect(signals).not.toBeNull();
    expect(signals?.map((s) => s.id).sort()).toEqual(["address", "date", "interseal"]);
  });

  it("요건마다 자기 자신의 body/precedents만 담는다 — 다른 요건과 섞이지 않는다", () => {
    const signals = parseSignals(decedentEstateData())!;
    const address = signals.find((s) => s.id === "address")!;
    const date = signals.find((s) => s.id === "date")!;

    expect(address.body).toContain("주소");
    expect(address.precedents).toEqual([
      { case_no: "2012다71688", summary: "주소 누락 관련 판시 요지" },
    ]);
    // date에는 address의 판례가 섞여 들어오면 안 된다.
    expect(date.precedents ?? []).toHaveLength(0);
  });

  it("대문자 grade(GREEN/RED)를 올바른 SignalGrade로 매핑한다", () => {
    const signals = parseSignals(decedentEstateData())!;
    expect(signals.find((s) => s.id === "date")?.grade).toBe("green");
    expect(signals.find((s) => s.id === "address")?.grade).toBe("red");
  });

  it("requirements가 비어있거나 없으면 null을 반환한다", () => {
    expect(parseSignals({ decedent_estate: { requirements: {} } })).toBeNull();
    expect(parseSignals({ decedent_estate: {} })).toBeNull();
    expect(parseSignals({})).toBeNull();
  });
});
