import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { AssistantResponse } from "./AssistantResponse";
import type { ChatResponse } from "../../types";

// AgentCards가 내부적으로 useApp()을 쓴다 — 결과/후속질문 렌더만 검사하므로
// send는 스파이만 해두고 실제 네트워크로는 연결하지 않는다.
vi.mock("../../lib/appState", () => ({ useApp: () => ({ send: vi.fn(), loading: false }) }));

function pendingAmountResponse(reply: string): ChatResponse {
  return {
    reply,
    needs_review: false,
    agents: ["asset_organizer"],
    path: "standard",
    verification: null,
    contributions: [
      {
        agent: "asset_organizer",
        reply,
        data: {
          asset_organizer: {
            pending_amounts: [
              {
                kind: "asset_value",
                asset_type: "주식",
                segment: "주식",
                reason: "주식 금액이 언급되지 않음",
              },
            ],
          },
        },
      },
    ],
  } as unknown as ChatResponse;
}

function render(response: ChatResponse, interactive: boolean) {
  return renderToStaticMarkup(
    createElement(AssistantResponse, { response, interactive }),
  );
}

/**
 * 과거 assistant 턴의 follow-up 카드가 계속 활성화돼 있어 사용자가 이미
 * 다음 카테고리로 넘어간 뒤에도 그 과거 카드를 다시 제출할 수 있었던 버그
 * (stale follow-up) — interactive=false면 followup-block 자체를 렌더하지
 * 않아야 한다. 본문/결과 카드는 그대로 유지된다.
 */
describe("AssistantResponse — interactive 게이팅(stale follow-up 방지)", () => {
  it("interactive=true면 최신 턴의 follow-up 위젯(AmountInputCard)을 렌더한다", () => {
    const html = render(pendingAmountResponse("주식 금액을 알려주세요."), true);
    expect(html).toContain("몇 가지만 더 확인할게요");
    expect(html).toContain("이 금액으로 답하기");
    expect(html).toContain("금액을 몰라요");
  });

  it("interactive=false면 같은 데이터라도 follow-up 블록을 아예 렌더하지 않는다", () => {
    const html = render(pendingAmountResponse("주식 금액을 알려주세요."), false);
    expect(html).not.toContain("몇 가지만 더 확인할게요");
    expect(html).not.toContain("이 금액으로 답하기");
    expect(html).not.toContain("금액을 몰라요");
    // 본문(reply)과 에이전트 헤더는 과거 턴이어도 그대로 보여야 한다.
    expect(html).toContain("주식 금액을 알려주세요.");
  });
});
