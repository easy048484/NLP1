import { describe, expect, it } from "vitest";
import { normalizeChatResponse } from "./api";
import { parseShares, parseShareWarnings, parseTaxResult } from "./agentData";
import { shareFixture, taxFixture } from "./taxShareFixtures";

describe("parseTaxResult — last_result 계약", () => {
  it("flatten된 실제 응답 필드를 기존 세액 내역 카드로 연결한다", () => {
    const state = taxFixture();
    const parsed = parseTaxResult(state, "tax_calculator");
    expect(parsed?.rows).toEqual([
      { label: "총상속재산", amount: 1_500_000_000 },
      { label: "차감 비용", amount: 5_000_000 },
      { label: "상속세 과세가액", amount: 1_495_000_000 },
      { label: "상속공제 합계", amount: 1_000_000_000 },
      { label: "과세표준", amount: 495_000_000 },
      { label: "산출세액", amount: 89_000_000 },
      { label: "신고세액공제", amount: 2_670_000 },
      { label: "최종 예상 상속세", amount: 86_330_000 },
    ]);
    expect(parsed?.final_amount).toBe(86_330_000);
    expect(parsed?.notes).toEqual(state.last_result.warnings);
    expect(parsed?.filing_due).toBeNull();
  });

  it("정상 계산된 0원을 결과 없음으로 취급하지 않는다", () => {
    const state = taxFixture();
    state.last_result.estimated_tax_due = 0;
    state.last_result.inheritance_tax_base = 0;
    state.last_result.calculated_inheritance_tax = 0;
    state.last_result.filing_tax_credit = 0;
    expect(parseTaxResult(state)?.final_amount).toBe(0);
  });

  it.each(["collecting", "unsupported", "needs_review", "needs_input_review", undefined])(
    "status=%s이면 지난 턴 last_result가 있어도 숨긴다",
    (status) => expect(parseTaxResult({ ...taxFixture(), status })).toBeNull(),
  );

  it.each([null, undefined, "0", -1, NaN, Infinity, 0.5, Number.MAX_SAFE_INTEGER + 1])(
    "유효하지 않은 최종금액 %s를 0원으로 바꾸거나 다른 값에서 추정하지 않는다",
    (value) => {
      const state = taxFixture();
      expect(parseTaxResult({
        ...state, last_result: { ...state.last_result, estimated_tax_due: value },
      })).toBeNull();
    },
  );

  it("필수 금액이 빠지면 카드 대신 합성 답변을 유지한다", () => {
    const state = taxFixture();
    expect(parseTaxResult({
      ...state, last_result: { ...state.last_result, filing_tax_credit: undefined },
    })).toBeNull();
  });

  it("명시적인 last_result:null을 레거시 result로 우회하지 않는다", () => {
    expect(parseTaxResult({
      status: "calculated", last_result: null,
      result: { rows: [{ label: "지난 값", amount: 123 }] },
    })).toBeNull();
  });

  it("추가 내역이 없는 최소 계약도 표시하되 없는 항목을 0으로 채우지 않는다", () => {
    const state = taxFixture();
    const parsed = parseTaxResult({ ...state, last_result: {
      ...state.last_result, deductible_expenses: undefined,
      taxable_inheritance_value: undefined, total_inheritance_deduction: undefined,
    } });
    expect(parsed?.rows).toHaveLength(5);
    expect(parsed?.rows.some((r) => r.label === "차감 비용")).toBe(false);
  });

  it("신고기한과 안내 문구를 안전하게 읽는다", () => {
    const state = taxFixture();
    const result = { ...state.last_result, estimated_filing_deadline: "2027-02-28",
      warnings: ["확인 필요", null, 123, ""] };
    expect(parseTaxResult({ ...state, last_result: result })).toMatchObject({
      filing_due: "2027-02-28", notes: ["확인 필요"],
    });
    result.estimated_filing_deadline = "2027-02-30";
    expect(parseTaxResult({ ...state, last_result: result })?.filing_due).toBeNull();
  });

  it("구 응답의 자기 namespace만 호환하고 다른 에이전트는 읽지 않는다", () => {
    const state = taxFixture();
    expect(parseTaxResult({ tax_calculator: state })).toEqual(parseTaxResult(state));
    expect(parseTaxResult(state, "decedent_estate")).toBeNull();
    expect(parseTaxResult({ retirement_planner: state })).toBeNull();
    expect(parseTaxResult({ ...state, tax_calculator: null })).toBeNull();
  });
});

describe("parseShares — last_result.heirs 계약", () => {
  it("분수와 금액을 프론트에서 재계산하지 않고 그대로 보존한다", () => {
    const state = shareFixture();
    const parsed = parseShares(state, "heir_share_analyzer");
    expect(parsed).toHaveLength(3);
    expect(parsed?.[0]).toMatchObject({
      heir: "배우자", relation: "spouse",
      statutory: "3/7 · 300,000,000원",
      forced: "법정상속분의 1/2 · 150,000,000원",
      statutory_share_fraction: "3/7", statutory_share_amount: 300_000_000,
      forced_share_rate_fraction: "1/2", basic_forced_share_estimate: 150_000_000,
      planned_acquisition: 0, simple_gap: 150_000_000,
    });
    expect(parsed?.[1].simple_gap).toBe(0);
    expect(parseShareWarnings(state)).toEqual(state.last_result.warnings);
  });

  it("미입력(null)과 실제 0원을 구분한다", () => {
    const state = shareFixture();
    state.last_result.heirs[2].planned_acquisition = null;
    state.last_result.heirs[2].simple_gap = null;
    const parsed = parseShares(state);
    expect(parsed?.[0].planned_acquisition).toBe(0);
    expect(parsed?.[1].simple_gap).toBe(0);
    expect(parsed?.[2]).toMatchObject({ planned_acquisition: null, simple_gap: null });
  });

  it.each(["basic_estimate", "no_simple_gap", "possible_gap", "expert_review_required"])(
    "계산 결과가 있는 %s 상태를 표시한다",
    (status) => {
      const state = shareFixture();
      state.status = status;
      state.last_result.status = status;
      expect(parseShares(state)).toHaveLength(3);
    },
  );

  it.each(["collecting", "collecting_family", "needs_input_review", undefined])(
    "미완료 상태 %s에 남아 있는 예전 표는 숨긴다",
    (status) => expect(parseShares({ ...shareFixture(), status })).toBeNull(),
  );

  it("미지원/입력 오류/질문 중인 응답의 예전 표는 재사용하지 않는다", () => {
    const state = shareFixture();
    state.status = "expert_review_required";
    state.last_result.status = "expert_review_required";
    expect(parseShares({ ...state, last_error: "미지원 사례" })).toBeNull();
    expect(parseShares({ ...state, asked_slot: "estate_value" })).toBeNull();
    expect(parseShares({ ...state, missing_fields: ["debts"] })).toBeNull();
    expect(parseShareWarnings({ ...state, last_error: "미지원 사례" })).toEqual([]);
    expect(parseShares({ ...state, last_result: null })).toBeNull();
  });

  it.each([null, -1, "100000000", Infinity])(
    "잘못된 상속인 금액 %s가 있으면 일부 사람만 조용히 누락하지 않는다",
    (value) => {
      const state = shareFixture();
      const heirs = state.last_result.heirs.map((heir, i) => i === 1
        ? { ...heir, basic_forced_share_estimate: value } : heir);
      expect(parseShares({ ...state, last_result: { ...state.last_result, heirs } })).toBeNull();
    },
  );

  it("금액 비교값을 누락할 수는 있지만 잘못된 값을 입력하면 거부한다", () => {
    const state = shareFixture();
    const heirs = [{ ...state.last_result.heirs[0], simple_gap: "0" }];
    expect(parseShares({ ...state, last_result: { ...state.last_result, heirs } })).toBeNull();
  });

  it("빈 표와 잘못된 분수는 표시하지 않는다", () => {
    const state = shareFixture();
    expect(parseShares({ ...state, last_result: { ...state.last_result, heirs: [] } })).toBeNull();
    state.last_result.heirs[0].statutory_share_fraction = "3/0";
    expect(parseShares(state)).toBeNull();
  });

  it("자기 namespace만 호환하고 다른 contribution으로 새지 않는다", () => {
    const state = shareFixture();
    expect(parseShares({ heir_share_analyzer: state })).toEqual(parseShares(state));
    expect(parseShares(state, "tax_calculator")).toBeNull();
    expect(parseShares({ decedent_estate: state })).toBeNull();
  });
});

describe("normalizeChatResponse → 각 에이전트 카드", () => {
  it("같은 턴의 두 에이전트 결과를 flatten 후 각각 올바른 파서에 전달한다", () => {
    const tax = taxFixture();
    const shares = shareFixture();
    const response = normalizeChatResponse({
      reply: "합성 답변은 한 번만 표시합니다.",
      agents: ["tax_calculator", "heir_share_analyzer"],
      data: { tax_calculator: tax, heir_share_analyzer: shares },
    });
    expect(response?.contributions).toHaveLength(2);
    expect(response?.reply).toBe("합성 답변은 한 번만 표시합니다.");
    const [taxContribution, shareContribution] = response!.contributions;
    expect(taxContribution.data).toEqual(tax);
    expect(shareContribution.data).toEqual(shares);
    expect(taxContribution.reply).toBe("");
    expect(shareContribution.reply).toBe("");
    expect(parseTaxResult(taxContribution.data, taxContribution.agent)?.final_amount).toBe(86_330_000);
    expect(parseShares(shareContribution.data, shareContribution.agent)).toHaveLength(3);
    expect(parseShares(taxContribution.data, taxContribution.agent)).toBeNull();
    expect(parseTaxResult(shareContribution.data, shareContribution.agent)).toBeNull();
  });
});
