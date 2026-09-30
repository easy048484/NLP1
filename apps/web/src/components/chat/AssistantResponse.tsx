import { useApp } from "../../lib/appState";
import { agentMeta } from "../../lib/agents";
import { Markdown } from "../../lib/markdown";
import type { ChatResponse } from "../../types";
import {
  hasAssetAmountRequest,
  hasAssetReview,
  hasCategorySelectionRequest,
  hasPendingQuestions,
} from "../../lib/agentData";
import { parseConfirmChecklist, parseReplySections } from "../../lib/replySections";
import { AgentAvatar, ConcatNoticeBadge, NeedsReviewBadge } from "../ui";
import { AgentCards } from "./AgentCards";
import { ConfirmChecklistCard } from "./ConfirmChecklistCard";
import { ReplyCarousel } from "./ReplyCarousel";
import { SuggestedActionCard } from "./SuggestedActionCard";

/**
 * 답변 본문을 어떻게 보여줄지 고른다 — 셋 다 순수 텍스트 휴리스틱(백엔드
 * 계약 변경 없음)이라 패턴이 안 맞으면 항상 기존 마크다운 그대로 폴백한다.
 * 우선순위: 확인 질문 체크리스트 > 섹션 캐러셀 > 원문.
 */
function renderReply(reply: string) {
  const checklist = parseConfirmChecklist(reply);
  if (checklist) return <ConfirmChecklistCard data={checklist} />;

  const sections = parseReplySections(reply);
  if (sections) {
    return (
      <ReplyCarousel
        intro={sections.intro}
        sections={sections.sections}
        footer={sections.footer}
        footerQuestion={sections.footerQuestion}
      />
    );
  }

  return <Markdown>{reply}</Markdown>;
}

/**
 * 합성(compose) 응답 한 건.
 * - 응답한 에이전트 아이덴티티 헤더 (아바타 + 이름)
 * - needs_review 배지
 * - 본문 마크다운 (서술만) — 담당 에이전트색 좌측 라인
 * - 기여별 근거 카드
 *
 * `interactive`는 이 응답이 대화의 가장 마지막 assistant 턴인지를
 * 나타낸다(MessageList가 계산해서 넘겨준다) — false면 본문/결과 카드는
 * 그대로 보이되 follow-up(AmountInputCard/AssetCategorySelectCard/
 * RemainingCategoriesPrompt/ChoiceGroup) 블록 자체를 렌더하지 않는다.
 * 실측 재현된 버그: 과거 턴의 follow-up 카드가 계속 렌더돼 있으면,
 * 사용자가 이미 다음 카테고리로 넘어간 뒤에도 그 과거 카드를 수정해
 * 다시 제출할 수 있었고, 그 답이 현재 pending 중인(다른) 카테고리에
 * 잘못 반영됐다.
 */
export function AssistantResponse({
  response,
  interactive,
}: {
  response: ChatResponse;
  interactive: boolean;
}) {
  const { send, loading } = useApp();
  const agents = dedupeAgents(response);
  const followups = interactive
    ? response.contributions.filter(
        (c) =>
          hasPendingQuestions(c.data ?? {}, c.agent) ||
          hasAssetAmountRequest(c.data ?? {}, c.agent) ||
          hasAssetReview(c.data ?? {}, c.agent) ||
          hasCategorySelectionRequest(c.data ?? {}, c.agent),
      )
    : [];
  // suggested_actions는 자동 handoff가 아니라 opt-in 제안이다 — 버튼을 눌러야만
  // action.message가 새 user_message로 전송된다(useApp().send). followups와
  // 동일하게 interactive(가장 마지막 assistant 턴)일 때만 렌더해, 과거 턴의
  // 제안 버튼이 계속 눌릴 수 있는 stale-control 버그를 막는다.
  const suggestedActions = interactive
    ? response.contributions.flatMap((c) => c.suggested_actions ?? [])
    : [];
  // asset_organizer의 review 화면(AssetReviewCard)은 이미 자기 reply
  // 텍스트("재산·부채를 확인해주세요")로 안내를 담고 있어, 일반
  // follow-up 머리말("몇 가지만 더 확인할게요")을 그 위에 또 붙이면
  // 중복으로 보인다 — 이번 턴 follow-up이 전부 review일 때만 생략한다.
  const isReviewOnly =
    followups.length > 0 &&
    followups.every((c) => hasAssetReview(c.data ?? {}, c.agent));

  return (
    <div className="assistant-response">
      {agents.length > 0 && (
        <div className="agent-header">
          <span className="agent-header-avatars">
            {agents.map((a) => (
              <AgentAvatar key={a} agent={a} size="sm" />
            ))}
          </span>
          <span className="agent-header-label">
            {agents.length === 1
              ? agentMeta(agents[0]).label
              : `${agents.length}개 영역 에이전트`}
            <span className="agent-header-sub"> 에이전트</span>
          </span>
        </div>
      )}

      {response.needs_review && <NeedsReviewBadge />}
      {!response.needs_review && response.verification?.mode === "concat" && (
        <ConcatNoticeBadge />
      )}

      {response.reply && (
        <div className="assistant-bubble">{renderReply(response.reply)}</div>
      )}

      {response.contributions.map((c, i) => (
        <AgentCards key={`${c.agent}-${i}`} contribution={c} mode="results" />
      ))}

      {suggestedActions.map((action, i) => (
        <SuggestedActionCard
          key={`suggested-action-${i}`}
          action={action}
          disabled={loading}
          onSelect={() => void send(action.message)}
        />
      ))}

      {followups.length > 0 && (
        <div className="followup-block">
          {!isReviewOnly && (
            <p className="followup-head">몇 가지만 더 확인할게요</p>
          )}
          {followups.map((c, i) => (
            <AgentCards
              key={`fq-${c.agent}-${i}`}
              contribution={c}
              mode="questions"
            />
          ))}
        </div>
      )}
    </div>
  );
}

function dedupeAgents(response: ChatResponse): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const c of response.contributions) {
    if (seen.has(c.agent)) continue;
    seen.add(c.agent);
    out.push(c.agent);
  }
  return out.filter(
    (a) => agentMeta(a).shortLabel !== "안내" || response.contributions.length === 1,
  );
}
