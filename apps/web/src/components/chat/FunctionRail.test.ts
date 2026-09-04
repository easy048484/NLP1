import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

/**
 * asset_organizer "자산 정리" 타일이 생전/사후 두 화면 모두에 보이는지,
 * 화면별 문구가 정확히 바뀌는지 확인한다 — 클릭 시 context.mode 전달
 * 자체는 SSR 렌더로는 검증할 수 없어(이벤트 핸들러 실행 불가) 백엔드
 * 쪽 실제 실행 테스트(test_asset_organizer_agent.py)로 검증했다.
 */
let mockAxis: "pre_need" | "post_death" | null = null;

vi.mock("../../lib/appState", () => ({
  useApp: () => ({ turns: [], axis: mockAxis, send: vi.fn(), loading: false }),
}));

import { FunctionRail } from "./FunctionRail";

function render(axis: "pre_need" | "post_death" | null) {
  mockAxis = axis;
  return renderToStaticMarkup(createElement(FunctionRail));
}

describe("FunctionRail — 자산 정리 타일 생전/사후 노출", () => {
  it("pre_need 화면에 자산 정리 타일과 생전 문구를 보여준다", () => {
    const html = render("pre_need");
    expect(html).toContain("자산 정리");
    expect(html).toContain("예금·보험·부동산 등 재산과 부채를 한눈에 정리");
    expect(html).not.toContain("은퇴 자금");
    expect(html).not.toContain(
      "고인의 재산·부채와 안심상속 조회 결과를 한눈에 정리",
    );
  });

  it("post_death 화면에도 자산 정리 타일을 보여주고 사후 문구를 쓴다", () => {
    const html = render("post_death");
    expect(html).toContain("자산 정리");
    expect(html).toContain(
      "고인의 재산·부채와 안심상속 조회 결과를 한눈에 정리",
    );
    expect(html).not.toContain("예금·보험·부동산 등 재산과 부채를 한눈에 정리");
  });

  it("post_death 화면에서는 post_death 전용 타일(상속 절차 안내/유류분)이 그대로 노출된다", () => {
    const html = render("post_death");
    expect(html).toContain("상속 절차 안내");
    expect(html).toContain("법정상속분");
  });

  it("pre_need 화면에서는 post_death 전용 타일(상속 절차 안내/유류분)이 보이지 않는다", () => {
    const html = render("pre_need");
    expect(html).not.toContain("상속 절차 안내");
    expect(html).not.toContain("법정상속분");
  });
});
