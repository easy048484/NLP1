import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { AssistantResponse } from "./AssistantResponse";
import { SuggestedActionCard } from "./SuggestedActionCard";
import type { ChatResponse, SuggestedAction } from "../../types";

// AgentCards/AssistantResponse가 내부적으로 useApp()을 쓴다 — appState는
// vi.hoisted로 고정해둬서(테스트마다 useApp()이 새 vi.fn()을 만들지 않게)
// send 호출 자체를 검증할 수 있게 한다(mockSend). loading은 테스트별로
// 직접 바꿔 "중복 클릭 방지" disabled 상태를 확인한다.
const { mockSend, appState } = vi.hoisted(() => {
  const mockSend = vi.fn();
  const appState = { send: mockSend, loading: false };
  return { mockSend, appState };
});
vi.mock("../../lib/appState", () => ({ useApp: () => appState }));

beforeEach(() => {
  mockSend.mockClear();
  appState.loading = false;
});

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

// suggested_actions (decedent_estate → heir_share_analyzer opt-in CTA)

const CTA_PROMPT = "유언 내용이 상속인의 유류분에 영향을 줄 수 있는지 참고용으로 확인해 볼까요?";
const CTA_LABEL = "유류분 영향 확인하기";
const CTA_MESSAGE = "유언 내용이 상속인의 유류분에 영향을 줄 수 있는지 확인해 주세요.";

function completedReviewResponse(
  suggestedActions: SuggestedAction[] | undefined,
): ChatResponse {
  return {
    reply: "형식 요건상 문제가 발견되지 않았습니다.",
    needs_review: false,
    agents: ["decedent_estate"],
    path: "standard",
    verification: null,
    contributions: [
      {
        agent: "decedent_estate",
        reply: "형식 요건상 문제가 발견되지 않았습니다.",
        data: {},
        suggested_actions: suggestedActions,
      },
    ],
  } as unknown as ChatResponse;
}

function ctaResponse(): ChatResponse {
  return completedReviewResponse([
    { prompt: CTA_PROMPT, label: CTA_LABEL, message: CTA_MESSAGE },
  ]);
}

/** AssistantResponse가 반환한 (아직 렌더되지 않은) React 엘리먼트 트리에서
 * SuggestedActionCard 엘리먼트를 찾는다 — 이 저장소의 vitest 설정은
 * environment: "node"라 jsdom/fireEvent가 없다(기존 테스트도 전부
 * renderToStaticMarkup 문자열 검사만 쓴다). 버튼 클릭이 실제로 무엇을
 * 보내는지 확인하려면 onSelect prop을 직접 호출하는 수밖에 없어, 트리를
 * 얕게 순회해 타입이 일치하는 엘리먼트를 찾는다. */
function findSuggestedActionElement(
  node: unknown,
): { props: { onSelect: () => void; disabled?: boolean } } | null {
  if (node == null || typeof node !== "object") return null;
  if (Array.isArray(node)) {
    for (const child of node) {
      const found = findSuggestedActionElement(child);
      if (found) return found;
    }
    return null;
  }
  const el = node as { type?: unknown; props?: Record<string, unknown> };
  if (el.type === SuggestedActionCard) {
    return el as unknown as { props: { onSelect: () => void; disabled?: boolean } };
  }
  if (el.props && "children" in el.props) {
    return findSuggestedActionElement(el.props.children);
  }
  return null;
}

describe("AssistantResponse — suggested_actions(유류분 opt-in CTA)", () => {
  it("interactive=true면 완료된 review 뒤에 CTA(prompt+버튼)를 렌더한다", () => {
    const html = render(ctaResponse(), true);
    expect(html).toContain(CTA_PROMPT);
    expect(html).toContain(CTA_LABEL);
  });

  it("interactive=false면 같은 데이터라도 CTA를 렌더하지 않는다(과거 턴 stale-control 방지)", () => {
    const html = render(ctaResponse(), false);
    expect(html).not.toContain(CTA_PROMPT);
    expect(html).not.toContain(CTA_LABEL);
    // 본문은 과거 턴이어도 그대로 보여야 한다.
    expect(html).toContain("형식 요건상 문제가 발견되지 않았습니다.");
  });

  it("suggested_actions가 없으면(기존 백엔드) CTA 없이 기존 UI 그대로다", () => {
    const html = render(completedReviewResponse(undefined), true);
    expect(html).not.toContain(CTA_LABEL);
    expect(html).toContain("형식 요건상 문제가 발견되지 않았습니다.");
  });

  it("버튼 클릭 시 action.message가 그대로 send된다 — 자동 handoff가 아니라 opt-in이다", () => {
    const tree = AssistantResponse({ response: ctaResponse(), interactive: true });
    const found = findSuggestedActionElement(tree);
    expect(found).not.toBeNull();

    found!.props.onSelect();

    expect(mockSend).toHaveBeenCalledTimes(1);
    expect(mockSend).toHaveBeenCalledWith(CTA_MESSAGE);
  });

  it("loading 중에는 버튼이 disabled라 중복 클릭을 막는다", () => {
    appState.loading = true;
    const html = render(ctaResponse(), true);
    // Button 컴포넌트는 disabled prop을 그대로 <button disabled> 로 넘긴다.
    const buttonSection = html.slice(html.indexOf(CTA_LABEL) - 200, html.indexOf(CTA_LABEL));
    expect(buttonSection).toContain("disabled");
  });
});
