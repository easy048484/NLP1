import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { AgentCards } from "./AgentCards";
import { shareFixture, taxFixture } from "../../lib/taxShareFixtures";
import type { AgentName } from "../../types";

// 결과 카드 표시만 검사한다. 로그인·API·공유 DB에는 연결하지 않는다.
vi.mock("../../lib/appState", () => ({ useApp: () => ({ send: vi.fn() }) }));

function render(
  agent: AgentName,
  data: Record<string, unknown>,
  mode: "results" | "questions" = "results",
) {
  return renderToStaticMarkup(createElement(AgentCards, {
    contribution: { agent, reply: "", data },
    mode,
  }));
}

describe("AgentCards — 상속세·유류분 결과 렌더", () => {
  it("상속세 내역과 백엔드 경고를 표시한다", () => {
    const html = render("tax_calculator", taxFixture());
    expect(html).toContain("상속세 시산");
    expect(html).toContain("86,330,000원");
    expect(html).toContain("신고세액공제");
    expect(html).toContain("상속개시일이 없어 신고기한을 계산하지 않았습니다.");
    expect(html).not.toContain("법정상속분 · 유류분");
  });

  it("유류분 표의 분수·금액·경고와 null/0 구분을 표시한다", () => {
    const state = shareFixture();
    state.last_result.heirs[2].planned_acquisition = null;
    state.last_result.heirs[2].simple_gap = null;
    const html = render("heir_share_analyzer", state);
    expect(html).toContain("법정상속분 · 유류분");
    expect(html).toContain("법정상속분의 1/2");
    expect(html).toContain("300,000,000원");
    expect(html).toContain("<td>0원</td>");
    expect(html).toContain("미확인");
    expect(html).toContain("비교 전");
    expect(html).toContain("최종 반환금액을 뜻하지 않으며 전문가 검토가 필요");
    expect(html).toContain(state.last_result.warnings[1]);
    expect(html).not.toContain("상속세 시산");
  });

  it("정상 0원은 표시하고 수집 중에는 결과 카드를 만들지 않는다", () => {
    const tax = taxFixture();
    tax.last_result.estimated_tax_due = 0;
    expect(render("tax_calculator", tax)).toContain("0원");
    expect(render("tax_calculator", { ...tax, status: "collecting" })).toBe("");
    expect(render("heir_share_analyzer", { ...shareFixture(), status: "collecting" })).toBe("");
  });

  it("다른 에이전트 카드 영역에 세금/유류분 표를 중복 표시하지 않는다", () => {
    expect(render("decedent_estate", {
      tax_calculator: taxFixture(), heir_share_analyzer: shareFixture(),
    })).toBe("");
  });
});

/**
 * asset_organizer가 특정 카테고리 금액을 되묻는 중이면(pending_amounts)
 * 금액 입력 위젯(AmountInputCard)을 렌더한다 — 카테고리 나열 선택지
 * (pending_categories)보다 우선한다(둘은 백엔드에서 서로 배타적).
 */
describe("AgentCards — asset_organizer 금액 입력 위젯", () => {
  it("pending_amounts가 있으면 금액 입력 위젯을 렌더한다(단위 필드 + 몰라요 버튼)", () => {
    const data = {
      asset_organizer: {
        pending_amounts: [
          { kind: "asset_value", asset_type: "예금", segment: "예금", reason: "예금 금액이 언급되지 않음" },
        ],
      },
    };
    const html = render("asset_organizer", data, "questions");
    expect(html).toContain("예금 금액");
    expect(html).toContain("억");
    expect(html).toContain("천만");
    expect(html).toContain("백만");
    expect(html).toContain("십만");
    expect(html).toContain("금액을 몰라요");
    expect(html).toContain("이 금액으로 답하기");
    expect(html).toContain("직접 숫자로 입력하기");
  });

  it("liability_value면 부채 유형 이름을 라벨로 쓴다", () => {
    const data = {
      asset_organizer: {
        pending_amounts: [
          { kind: "liability_value", liability_type: "대출", segment: "대출", reason: "대출 금액이 언급되지 않음" },
        ],
      },
    };
    expect(render("asset_organizer", data, "questions")).toContain("대출 금액");
  });

  it("insurance_value면 보험 금액 입력 위젯을 렌더한다(AmountInputCard 재사용)", () => {
    const data = {
      asset_organizer: {
        pending_amounts: [
          { kind: "insurance_value", asset_type: "보험", segment: "보험", reason: "보험 금액이 언급되지 않음" },
        ],
      },
    };
    const html = render("asset_organizer", data, "questions");
    expect(html).toContain("보험 금액");
    expect(html).toContain("이 금액으로 답하기");
    expect(html).toContain("금액을 몰라요");
  });

  it("pending_amounts가 비어 있고 pending_categories만 있으면 남은 카테고리 일괄 확인 위젯을 쓴다", () => {
    const data = {
      asset_organizer: { pending_amounts: [], pending_categories: ["주식", "펀드"] },
    };
    const html = render("asset_organizer", data, "questions");
    expect(html).toContain("주식, 펀드");
    expect(html).toContain("네, 모두 없어요");
    expect(html).toContain("더 있어요");
    expect(html).not.toContain("이 금액으로 답하기");
  });

  it("아무 후속 질문도 없으면 빈 문자열이다", () => {
    expect(render("asset_organizer", { asset_organizer: {} }, "questions")).toBe("");
  });
});

/**
 * "자산 정리하고 싶어요"처럼 시작 의사만 있고 구체적 항목이 없을 때
 * (awaiting_category_selection) 카테고리 다중 선택 UI를 렌더한다 —
 * 파싱 실패 재질문 대신 진입 UX를 뚫어주는 게 목적이라 다른 후속
 * 질문보다 먼저 확인해야 한다(단, pending_amounts가 있으면 그게 우선).
 */
describe("AgentCards — 자산정리 카테고리 선택 위젯", () => {
  it("awaiting_category_selection이면 전체 카테고리(예금·적금~대출·기타 부채, 기타 포함) 선택 UI를 렌더한다", () => {
    const data = { asset_organizer: { awaiting_category_selection: true } };
    const html = render("asset_organizer", data, "questions");
    expect(html).toContain("여러 개 선택할 수 있어요");
    expect(html).toContain("예금·적금");
    expect(html).toContain("주식");
    expect(html).toContain("펀드");
    expect(html).toContain("부동산");
    expect(html).toContain("자동차");
    expect(html).toContain("퇴직연금");
    expect(html).toContain("보험");
    expect(html).toContain("기타");
    expect(html).toContain("대출·기타 부채");
    expect(html).toContain("선택 완료");
  });

  it("pending_amounts가 있으면 카테고리 선택보다 금액 입력 위젯을 우선한다", () => {
    const data = {
      asset_organizer: {
        awaiting_category_selection: true,
        pending_amounts: [
          { kind: "asset_value", asset_type: "예금", segment: "예금", reason: "예금 금액이 언급되지 않음" },
        ],
      },
    };
    const html = render("asset_organizer", data, "questions");
    expect(html).toContain("이 금액으로 답하기");
    expect(html).not.toContain("선택 완료");
  });

  it("더 있어요를 누르기 전에는 남은 카테고리로 좁힌 선택 UI가 안 보인다", () => {
    const data = {
      asset_organizer: { pending_categories: ["주식", "펀드", "자동차", "퇴직연금", "보험"] },
    };
    const html = render("asset_organizer", data, "questions");
    // 초기 렌더는 두 버튼만 보여준다 — 선택 그리드는 "더 있어요" 클릭 후에만
    // 나타난다(useState 초기값 검증, 클릭 시뮬레이션은 SSR로는 불가능).
    expect(html).not.toContain("선택 완료");
  });
});

/**
 * 수집이 끝나면(status==="reviewing") 즉시 finalized로 넘어가지 않고
 * 항목별 확인/수정 화면(AssetReviewCard)을 보여준다 — 기존 AmountInputCard
 * 위젯들과 마찬가지로 mode="questions"에서만 렌더된다.
 */
describe("AgentCards — 자산정리 review(수집 완료 후 확인/수정) 위젯", () => {
  it("status가 reviewing이면 항목 표와 [수정]/[이대로 확정] 버튼을 렌더한다", () => {
    const data = {
      asset_organizer: {
        status: "reviewing",
        review_items: [
          {
            kind: "asset_value",
            type: "주식",
            label: "주식",
            value: 15_000_000,
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
    const html = render("asset_organizer", data, "questions");
    expect(html).toContain("주식");
    expect(html).toContain("보험");
    expect(html).toContain("금액 미확인");
    expect(html).toContain("수정");
    expect(html).toContain("이대로 확정");
    // 보험 행 자체에는 "(합계 제외)"를 붙이지 않는다 — "보험은 재산이
    // 아닌가?"로 오해하기 쉬웠던 표현(실측 피드백 반영). 대신 카드 하단에
    // 안내문을 한 번만 보여준다.
    expect(html).not.toContain("합계 제외");
    expect(html).toContain(
      "보험은 금액의 성격(해약환급금·보험금 등)과 계약 관계에 따라",
    );
  });

  it("excludedFromTotals 항목이 없으면 안내문을 표시하지 않는다", () => {
    const data = {
      asset_organizer: {
        status: "reviewing",
        review_items: [
          {
            kind: "asset_value",
            type: "예금",
            label: "예금",
            value: 42_000_000,
            confidence: "confirmed",
            target: { kind: "asset_value", asset_type: "예금" },
          },
        ],
      },
    };
    const html = render("asset_organizer", data, "questions");
    expect(html).toContain("예금");
    expect(html).not.toContain("보험은 금액의 성격");
  });

  it("editing_item 중(pending_amounts만 있음)에는 review 표 대신 기존 AmountInputCard를 렌더한다", () => {
    const data = {
      asset_organizer: {
        status: "editing_item",
        pending_amounts: [{ kind: "asset_value", asset_type: "주식" }],
      },
    };
    const html = render("asset_organizer", data, "questions");
    expect(html).toContain("이 금액으로 답하기");
    expect(html).not.toContain("이대로 확정");
  });
});
