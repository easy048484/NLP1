import { describe, expect, it } from "vitest";
import {
  hasPendingQuestions,
  parsePendingQuestions,
  parseShares,
  parseSignals,
  parseTaxResult,
} from "./agentData";

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

  it("현재 agent(decedent_estate) namespace에 requirements가 없으면 다른 agent namespace의 값을 대신 보여주면 안 된다", () => {
    const data = {
      decedent_estate: { will_type: "handwritten" },
      heir_navigator: {
        requirements: {
          other: { id: "other", name: "다른 요건", grade: "GREEN", body: "다른 에이전트 값" },
        },
      },
    };
    // decedent_estate 카드를 렌더링 중인 상황을 가정(agentKey 전달) — 이
    // 카드는 자기 요건이 없으므로 "유언 요건 점검" 카드 자체가 뜨면 안
    // 된다(다른 agent 값 유입 금지).
    expect(parseSignals(data, "decedent_estate")).toBeNull();
  });
});

describe("parseTaxResult / parseShares — 다른 agent namespace 오염 방지", () => {
  it("parseTaxResult: 현재(decedent_estate) namespace에 결과가 없으면 다른 agent(tax_calculator)의 값을 대신 보여주면 안 된다", () => {
    const data = {
      decedent_estate: { will_type: "handwritten" },
      tax_calculator: {
        result: { rows: [{ label: "과세표준", amount: 100 }], status: "calculated" },
      },
    };
    expect(parseTaxResult(data, "decedent_estate")).toBeNull();
  });

  it("parseShares: 현재(decedent_estate) namespace에 분배표가 없으면 다른 agent(heir_share_analyzer)의 값을 대신 보여주면 안 된다", () => {
    const data = {
      decedent_estate: { will_type: "handwritten" },
      heir_share_analyzer: {
        shares: [{ heir: "배우자", statutory_share: "1.5/3.5" }],
      },
    };
    expect(parseShares(data, "decedent_estate")).toBeNull();
  });

  it("agentKey 없는 legacy 호출은 기존처럼 아무 namespace나 순회해서 찾는다", () => {
    const data = {
      tax_calculator: {
        result: { rows: [{ label: "과세표준", amount: 100 }], status: "calculated" },
      },
    };
    expect(parseTaxResult(data)?.final_amount).toBe(100);
  });
});

/**
 * 실제 tax_calculator/models.py InheritanceTaxResult 모양.
 * rows/final_amount/filing_due 같은 키는 없고 flat named int 만 온다 —
 * 예전 parseTaxResult 는 여기서 null 을 반환해 "상속세 시산" 카드가 아예
 * 안 떴다. contribution.data 는 state(= {status, last_result, ...}) 슬라이스.
 */
function taxCalculatorData() {
  return {
    status: "calculated",
    last_result: {
      total_inherited_property: 1_000_000_000,
      deductible_expenses: 50_000_000,
      taxable_inheritance_value: 950_000_000,
      total_inheritance_deduction: 700_000_000,
      inheritance_tax_base: 250_000_000,
      calculated_inheritance_tax: 40_000_000,
      filing_tax_credit: 1_200_000,
      estimated_tax_due: 38_800_000,
      estimated_filing_deadline: "2026-08-31",
      warnings: ["돌아가신 날짜를 입력하지 않아 신고기한은 계산하지 않았어요."],
    },
  };
}

describe("parseTaxResult — 실제 InheritanceTaxResult(flat) 파싱", () => {
  it("flat named 필드로 내역 행을 만든다", () => {
    const tax = parseTaxResult(taxCalculatorData(), "tax_calculator");
    expect(tax).not.toBeNull();
    const labels = tax!.rows.map((r) => r.label);
    expect(labels).toContain("세금을 매기는 기준 금액");
    expect(tax!.rows.find((r) => r.label === "세금을 매기는 기준 금액")?.amount).toBe(
      250_000_000,
    );
  });

  it("최종세액은 estimated_tax_due, 신고기한은 estimated_filing_deadline 에서 온다", () => {
    const tax = parseTaxResult(taxCalculatorData(), "tax_calculator")!;
    expect(tax.final_amount).toBe(38_800_000);
    expect(tax.filing_due).toBe("2026-08-31");
  });

  it("status 는 last_result 가 아니라 부모 state 에서 읽는다", () => {
    const tax = parseTaxResult(taxCalculatorData(), "tax_calculator")!;
    expect(tax.status).toBe("calculated");
    const collecting = { ...taxCalculatorData(), status: "collecting" };
    expect(parseTaxResult(collecting, "tax_calculator")!.status).toBe("collecting");
  });

  it("warnings 를 notes 로 넘긴다", () => {
    const tax = parseTaxResult(taxCalculatorData(), "tax_calculator")!;
    expect(tax.notes?.[0]).toContain("신고기한은 계산하지 않았");
  });
});

/**
 * 실제 heir_share_analyzer/models.py HeirShareResult 모양.
 * 상속인 목록은 last_result.heirs (HeirShareBreakdown[]) 에 있고,
 * 필드명은 statutory_share_fraction / forced_share_rate_fraction.
 * 예전 parseShares 는 shares/distribution 만 봐서 카드가 안 떴다.
 */
function heirShareData() {
  return {
    status: "no_simple_gap",
    last_result: {
      basis_amount: 700_000_000,
      heirs: [
        {
          name: "김배우",
          relation: "spouse",
          statutory_share_fraction: "3/7",
          statutory_share_amount: 300_000_000,
          forced_share_rate_fraction: "1/2",
          basic_forced_share_estimate: 150_000_000,
        },
        {
          name: "김자녀",
          relation: "child",
          statutory_share_fraction: "2/7",
          statutory_share_amount: 200_000_000,
          forced_share_rate_fraction: "1/2",
          basic_forced_share_estimate: 100_000_000,
        },
      ],
    },
  };
}

describe("parseShares — 실제 HeirShareResult.heirs 파싱", () => {
  it("last_result.heirs 에서 상속인별 비율을 읽는다", () => {
    const shares = parseShares(heirShareData(), "heir_share_analyzer");
    expect(shares).not.toBeNull();
    expect(shares!.map((s) => s.heir)).toEqual(["김배우", "김자녀"]);
    expect(shares!.find((s) => s.heir === "김배우")).toMatchObject({
      statutory: "3/7",
      forced: "1/2",
    });
  });

  it("heirs 가 비어 있으면 null", () => {
    const empty = { last_result: { heirs: [] } };
    expect(parseShares(empty, "heir_share_analyzer")).toBeNull();
  });
});
