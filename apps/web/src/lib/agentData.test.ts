import { describe, expect, it } from "vitest";
import {
  hasAssetAmountRequest,
  hasAssetReview,
  hasCategorySelectionRequest,
  hasPendingQuestions,
  parseAssetAmountRequest,
  parseAssetReview,
  parsePendingQuestions,
  parseRemainingCategoriesPrompt,
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
 * asset_organizer가 특정 카테고리 금액을 되묻는 중인지(state.pending_amounts)
 * 확인하는 파서. 금액 입력 위젯(AmountInputCard)을 언제 보여줄지 결정한다.
 */
describe("parseAssetAmountRequest / hasAssetAmountRequest", () => {
  it("pending_amounts 첫 항목이 asset_value면 유형 라벨을 돌려준다", () => {
    const data = {
      asset_organizer: {
        pending_amounts: [
          { kind: "asset_value", asset_type: "예금", segment: "예금", reason: "예금 금액이 언급되지 않음" },
        ],
      },
    };
    expect(parseAssetAmountRequest(data, "asset_organizer")).toEqual({
      kind: "asset_value",
      label: "예금",
    });
    expect(hasAssetAmountRequest(data, "asset_organizer")).toBe(true);
  });

  it("liability_value면 liability_type을 라벨로 쓴다", () => {
    const data = {
      asset_organizer: {
        pending_amounts: [
          { kind: "liability_value", liability_type: "대출", segment: "대출", reason: "대출 금액이 언급되지 않음" },
        ],
      },
    };
    expect(parseAssetAmountRequest(data, "asset_organizer")).toEqual({
      kind: "liability_value",
      label: "대출",
    });
  });

  it("insurance_value면 asset_type(항상 '보험')을 라벨로 쓴다", () => {
    const data = {
      asset_organizer: {
        pending_amounts: [
          { kind: "insurance_value", asset_type: "보험", segment: "보험", reason: "보험 금액이 언급되지 않음" },
        ],
      },
    };
    expect(parseAssetAmountRequest(data, "asset_organizer")).toEqual({
      kind: "insurance_value",
      label: "보험",
    });
    expect(hasAssetAmountRequest(data, "asset_organizer")).toBe(true);
  });

  it("pending_amounts가 비어 있으면 null", () => {
    const data = { asset_organizer: { pending_amounts: [] } };
    expect(parseAssetAmountRequest(data, "asset_organizer")).toBeNull();
    expect(hasAssetAmountRequest(data, "asset_organizer")).toBe(false);
  });

  it("agentKey가 없으면(legacy 호출) null — 다른 agent namespace로 새지 않는다", () => {
    const data = {
      asset_organizer: {
        pending_amounts: [{ kind: "asset_value", asset_type: "예금" }],
      },
    };
    expect(parseAssetAmountRequest(data)).toBeNull();
  });

  it("다른 agent의 namespace에 pending_amounts가 있어도 자기 것이 아니면 안 읽는다", () => {
    const data = {
      asset_organizer: { pending_amounts: [{ kind: "asset_value", asset_type: "예금" }] },
    };
    expect(parseAssetAmountRequest(data, "tax_calculator")).toBeNull();
  });
});

/**
 * 수집이 끝나면(state.status === "reviewing") 백엔드가 항목별 표를
 * data.asset_organizer.review_items로 구조화해서 보내준다 — [수정] 클릭 시
 * 되돌려 보낼 target도 항목마다 함께 온다(agent.py._build_review_items).
 */
describe("parseAssetReview / hasAssetReview", () => {
  it("status가 reviewing이고 review_items가 있으면 항목들을 파싱한다", () => {
    const data = {
      asset_organizer: {
        status: "reviewing",
        review_items: [
          {
            kind: "asset_value",
            type: "주식",
            label: "주식",
            value: 600_000_000,
            confidence: "confirmed",
            target: { kind: "asset_value", asset_type: "주식" },
          },
          {
            kind: "insurance_value",
            type: "보험",
            label: "보험",
            value: null,
            confidence: "unknown_amount",
            target: { kind: "insurance_value", asset_type: "보험" },
            excluded_from_totals: true,
          },
        ],
      },
    };
    const review = parseAssetReview(data, "asset_organizer");
    expect(review?.items).toEqual([
      {
        kind: "asset_value",
        label: "주식",
        value: 600_000_000,
        confidence: "confirmed",
        target: { kind: "asset_value", asset_type: "주식" },
        excludedFromTotals: false,
      },
      {
        kind: "insurance_value",
        label: "보험",
        value: null,
        confidence: "unknown_amount",
        target: { kind: "insurance_value", asset_type: "보험" },
        excludedFromTotals: true,
      },
    ]);
    expect(hasAssetReview(data, "asset_organizer")).toBe(true);
  });

  it("status가 reviewing이 아니면 review_items가 있어도 null(예: editing_item 중 pending_amounts와 동시에 존재하지 않음)", () => {
    const data = {
      asset_organizer: {
        status: "editing_item",
        review_items: [
          { kind: "asset_value", label: "예금", value: 100, confidence: "confirmed", target: {} },
        ],
      },
    };
    expect(parseAssetReview(data, "asset_organizer")).toBeNull();
  });

  it("review_items가 비어 있으면 null", () => {
    expect(
      parseAssetReview({ asset_organizer: { status: "reviewing", review_items: [] } }, "asset_organizer"),
    ).toBeNull();
  });

  it("agentKey가 없으면 null", () => {
    const data = {
      asset_organizer: {
        status: "reviewing",
        review_items: [
          { kind: "asset_value", label: "예금", value: 100, confidence: "confirmed", target: {} },
        ],
      },
    };
    expect(parseAssetReview(data)).toBeNull();
  });
});

/**
 * "자산 정리하고 싶어요"처럼 시작 의사만 있고 구체적 항목이 없을 때
 * (agent.py의 state.awaiting_category_selection) 카테고리 선택 UI를
 * 보여줄지 판단하는 파서.
 */
describe("hasCategorySelectionRequest", () => {
  it("awaiting_category_selection이 true면 true", () => {
    const data = { asset_organizer: { awaiting_category_selection: true } };
    expect(hasCategorySelectionRequest(data, "asset_organizer")).toBe(true);
  });

  it("플래그가 없거나 false면 false", () => {
    expect(hasCategorySelectionRequest({ asset_organizer: {} }, "asset_organizer")).toBe(false);
    expect(
      hasCategorySelectionRequest(
        { asset_organizer: { awaiting_category_selection: false } },
        "asset_organizer",
      ),
    ).toBe(false);
  });

  it("agentKey가 없으면 false", () => {
    expect(
      hasCategorySelectionRequest({ asset_organizer: { awaiting_category_selection: true } }),
    ).toBe(false);
  });
});

/**
 * 선택 항목 입력 완료 후 남은 미확인 카테고리 일괄 확인
 * (agent.py의 state.pending_categories) — "네 모두 없어요"/"더 있어요"
 * 두 버튼 위젯(RemainingCategoriesPrompt)이 쓴다.
 */
describe("parseRemainingCategoriesPrompt", () => {
  it("pending_categories가 있으면 그대로 돌려준다", () => {
    const data = {
      asset_organizer: { pending_categories: ["주식", "펀드", "자동차", "퇴직연금", "보험"] },
    };
    expect(parseRemainingCategoriesPrompt(data, "asset_organizer")).toEqual({
      categories: ["주식", "펀드", "자동차", "퇴직연금", "보험"],
    });
  });

  it("비어 있으면 null", () => {
    expect(
      parseRemainingCategoriesPrompt({ asset_organizer: { pending_categories: [] } }, "asset_organizer"),
    ).toBeNull();
  });
});
