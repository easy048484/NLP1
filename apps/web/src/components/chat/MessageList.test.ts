import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { ChatResponse } from "../../types";
import type { Turn } from "../../lib/appState";

/**
 * 재현된 버그: 과거 assistant 턴(예: 주식 금액 되묻기)의 follow-up 카드가
 * 계속 렌더돼 있으면, 사용자가 이미 다음 카테고리(부동산) 질문으로 넘어간
 * 뒤에도 그 과거 카드를 수정해 재제출할 수 있었다 — AgentCards의 send는
 * 카테고리 구분 없이 값만 보내므로 현재 pending 중인 다른 카테고리에
 * 잘못 반영됐다. MessageList는 turns 배열에서 "가장 마지막 turn이
 * assistant 응답일 때만" 그 turn을 interactive로 표시해야 한다.
 */
let mockTurns: Turn[] = [];
let mockLoading = false;

vi.mock("../../lib/appState", () => ({
  useApp: () => ({ turns: mockTurns, loading: mockLoading }),
}));

import { MessageList } from "./MessageList";

function pendingAmountResponse(label: string): ChatResponse {
  return {
    reply: `${label} 금액을 알려주세요.`,
    needs_review: false,
    agents: ["asset_organizer"],
    path: "standard",
    verification: null,
    contributions: [
      {
        agent: "asset_organizer",
        reply: `${label} 금액을 알려주세요.`,
        data: {
          asset_organizer: {
            pending_amounts: [
              { kind: "asset_value", asset_type: label, segment: label, reason: `${label} 금액이 언급되지 않음` },
            ],
          },
        },
      },
    ],
  } as unknown as ChatResponse;
}

function render(turns: Turn[], loading = false) {
  mockTurns = turns;
  mockLoading = loading;
  return renderToStaticMarkup(createElement(MessageList));
}

describe("MessageList — 최신 assistant 턴만 interactive(stale follow-up 방지)", () => {
  it("과거 주식 카드(A)는 follow-up이 없고, 최신 부동산 카드(B)만 정상 입력 가능하다", () => {
    const turns: Turn[] = [
      { id: "u1", role: "user", text: "주식 있어요" },
      { id: "a1", role: "assistant", response: pendingAmountResponse("주식") },
      { id: "u2", role: "user", text: "6억" },
      { id: "a2", role: "assistant", response: pendingAmountResponse("부동산") },
    ];
    const html = render(turns);

    // 최신(a2, 부동산) follow-up은 정상 렌더된다 (E)
    expect(html).toContain("몇 가지만 더 확인할게요");
    expect(html).toContain("부동산 금액을 알려주세요.");
    // 과거(a1, 주식) 본문은 남아 있지만 follow-up 위젯은 없어야 한다 (A)
    expect(html).toContain("주식 금액을 알려주세요.");
    const followupBlocks = html.match(/몇 가지만 더 확인할게요/g) ?? [];
    expect(followupBlocks.length).toBe(1);
  });

  it("마지막 턴이 user(응답 대기 중)면 어떤 과거 assistant 턴도 interactive가 아니다", () => {
    const turns: Turn[] = [
      { id: "a1", role: "assistant", response: pendingAmountResponse("주식") },
      { id: "u2", role: "user", text: "1500만" },
    ];
    const html = render(turns, true);
    expect(html).not.toContain("몇 가지만 더 확인할게요");
    expect(html).not.toContain("이 금액으로 답하기");
  });

  it("과거 카테고리 선택(C)/일반 선택지(D) 위젯도 최신 턴이 아니면 렌더되지 않는다", () => {
    const categoryResponse: ChatResponse = {
      reply: "어떤 자산이 있으세요?",
      needs_review: false,
      agents: ["asset_organizer"],
      path: "standard",
      verification: null,
      contributions: [
        {
          agent: "asset_organizer",
          reply: "어떤 자산이 있으세요?",
          data: { asset_organizer: { awaiting_category_selection: true } },
        },
      ],
    } as unknown as ChatResponse;

    const choiceResponse: ChatResponse = {
      reply: "유언 방식을 알려주세요.",
      needs_review: false,
      agents: ["decedent_estate"],
      path: "standard",
      verification: null,
      contributions: [
        {
          agent: "decedent_estate",
          reply: "유언 방식을 알려주세요.",
          data: {
            decedent_estate: {
              pending_questions: [
                { question: "유언 방식을 알려주세요.", field: "will_type", options: [{ label: "자필", value: "holograph" }] },
              ],
            },
          },
        },
      ],
    } as unknown as ChatResponse;

    const laterAmountResponse = pendingAmountResponse("부동산");

    const turns: Turn[] = [
      { id: "a1", role: "assistant", response: categoryResponse },
      { id: "u2", role: "user", text: "예금이요" },
      { id: "a2", role: "assistant", response: choiceResponse },
      { id: "u3", role: "user", text: "그거로 할게요" },
      { id: "a3", role: "assistant", response: laterAmountResponse },
    ];
    const html = render(turns);

    // 과거 카테고리 선택(C)과 과거 ChoiceGroup(D) 위젯은 둘 다 사라져야 한다.
    expect(html).not.toContain("선택 완료");
    expect(html).not.toContain("자필");
    // 본문 텍스트는 과거 턴이어도 그대로 남는다.
    expect(html).toContain("유언 방식을 알려주세요.");
    // 최신(a3) follow-up만 활성 상태로 렌더된다.
    expect(html).toContain("몇 가지만 더 확인할게요");
    expect(html).toContain("부동산 금액을 알려주세요.");
  });

  it("과거 asset_organizer review 카드(수정/이대로 확정)는 최신 턴이 아니면 재클릭 불가", () => {
    const reviewResponse: ChatResponse = {
      reply: "재산·부채를 확인해주세요.",
      needs_review: false,
      agents: ["asset_organizer"],
      path: "standard",
      verification: null,
      contributions: [
        {
          agent: "asset_organizer",
          reply: "재산·부채를 확인해주세요.",
          data: {
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
              ],
            },
          },
        },
      ],
    } as unknown as ChatResponse;

    const turns: Turn[] = [
      { id: "a1", role: "assistant", response: reviewResponse },
      { id: "u2", role: "user", text: "예금 수정할게요" },
      { id: "a2", role: "assistant", response: pendingAmountResponse("예금") },
    ];
    const html = render(turns);

    // 과거 review 카드의 [수정]/[이대로 확정] 버튼은 사라지고, 본문만 남는다.
    expect(html).not.toContain("이대로 확정");
    expect(html).toContain("재산·부채를 확인해주세요.");
    // 최신 턴(수정 답변용 AmountInputCard)만 활성화된다.
    expect(html).toContain("이 금액으로 답하기");
  });
});
