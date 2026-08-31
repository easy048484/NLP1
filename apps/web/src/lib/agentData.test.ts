import { describe, expect, it } from "vitest";
import { hasPendingQuestions, parsePendingQuestions, parseSignals } from "./agentData";

/**
 * 오케스트레이터가 여러 에이전트를 한 턴에 실행하면 node_compose() 가
 * output.data 를 dict.update() 로 얕게 합치면서 최상위 평면
 * pending_questions 키를 마지막 에이전트 값으로 덮어쓴다(병합 버그,
 * 백엔드 팀 공유됨). 프론트는 최상위가 아니라 네임스페이스
 * (data[agent].pending_questions) 를 우선 읽어야 각 에이전트의
 * 질문을 정확히 구분해 보여줄 수 있다.
 */
describe("parsePendingQuestions", () => {
  it("여러 에이전트가 동시 응답해도 각자의 네임스페이스 질문을 읽는다", () => {
    const data = {
      // node_compose() 의 dict.update() 로 마지막에 덮어써진, 신뢰할 수 없는 최상위 값
      pending_questions: [
        { question: "상속세 신고 기한을 알고 싶으신가요?", field: "due_date" },
      ],
      decedent_estate: {
        pending_questions: [
          {
            question: "유언장에 도장을 찍으셨나요?",
            field: "seal_answer",
            options: [
              { label: "예", value: "seal_or_fingerprint" },
              { label: "아니오", value: "no_seal" },
            ],
          },
        ],
      },
      heir_navigator: {
        pending_questions: [
          { question: "피상속인의 자녀가 몇 명인가요?", field: "child_count" },
        ],
      },
    };

    const decedentEstateData = { decedent_estate: data.decedent_estate };
    const heirNavigatorData = { heir_navigator: data.heir_navigator };

    const decedentResult = parsePendingQuestions(
      {
        ...data,
        // decedent_estate 카드 렌더링 시엔 contribution.data 가 이렇게 넘어온다고 가정
        ...decedentEstateData,
      },
      "decedent_estate",
    );
    expect(decedentResult?.[0]?.question).toBe("유언장에 도장을 찍으셨나요?");
    expect(decedentResult?.[0]?.field).toBe("seal_answer");

    const heirResult = parsePendingQuestions(
      {
        ...data,
        ...heirNavigatorData,
      },
      "heir_navigator",
    );
    expect(heirResult?.[0]?.question).toBe("피상속인의 자녀가 몇 명인가요?");
  });

  it("네임스페이스에 값이 없으면 최상위 평면 키로 폴백한다", () => {
    const data = {
      pending_questions: [{ question: "폴백 질문", field: "x" }],
      some_other_agent: { note: "no pending_questions here" },
    };
    const result = parsePendingQuestions(data);
    expect(result?.[0]?.question).toBe("폴백 질문");
  });

  it("네임스페이스와 최상위 모두 없으면 null 을 반환한다", () => {
    expect(parsePendingQuestions({ decedent_estate: { body: "x" } })).toBeNull();
  });
});

describe("hasPendingQuestions", () => {
  it("여러 agent namespace가 동시에 있어도 agentKey로 지정한 자기 namespace만 반영한다", () => {
    const data = {
      decedent_estate: {
        pending_questions: [{ question: "유언장에 도장을 찍으셨나요?", field: "seal_answer" }],
      },
      heir_navigator: {
        note: "no pending_questions here",
      },
    };

    expect(hasPendingQuestions(data, "decedent_estate")).toBe(true);
    expect(hasPendingQuestions(data, "heir_navigator")).toBe(false);
  });

  it("다른 agent namespace에만 질문이 있으면 현재 agent는 false여야 한다", () => {
    const data = {
      decedent_estate: { note: "no pending_questions here" },
      heir_navigator: {
        pending_questions: [{ question: "피상속인의 자녀가 몇 명인가요?", field: "child_count" }],
      },
    };

    expect(hasPendingQuestions(data, "decedent_estate")).toBe(false);
    expect(hasPendingQuestions(data, "heir_navigator")).toBe(true);
  });

  it("agentKey 없이 호출하는 legacy 입력은 기존처럼 최상위/첫 네임스페이스로 동작한다", () => {
    const data = {
      pending_questions: [{ question: "폴백 질문", field: "x" }],
      some_other_agent: { note: "no pending_questions here" },
    };
    expect(hasPendingQuestions(data)).toBe(true);
    expect(hasPendingQuestions({ decedent_estate: { body: "x" } })).toBe(false);
  });
});

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
