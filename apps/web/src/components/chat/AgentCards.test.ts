import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { AgentCards } from "./AgentCards";
import { shareFixture, taxFixture } from "../../lib/taxShareFixtures";
import type { AgentName } from "../../types";

// 결과 카드 표시만 검사한다. 로그인·API·공유 DB에는 연결하지 않는다.
vi.mock("../../lib/appState", () => ({ useApp: () => ({ send: vi.fn() }) }));

function render(agent: AgentName, data: Record<string, unknown>) {
  return renderToStaticMarkup(createElement(AgentCards, {
    contribution: { agent, reply: "", data },
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
