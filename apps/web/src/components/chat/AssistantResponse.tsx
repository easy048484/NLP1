import { agentMeta } from "../../lib/agents";
import { Markdown } from "../../lib/markdown";
import type { ChatResponse } from "../../types";
import { hasAssetAmountRequest, hasPendingQuestions } from "../../lib/agentData";
import { parseConfirmChecklist, parseReplySections } from "../../lib/replySections";
import { AgentAvatar, ConcatNoticeBadge, NeedsReviewBadge } from "../ui";
import { AgentCards } from "./AgentCards";
import { ConfirmChecklistCard } from "./ConfirmChecklistCard";
import { ReplyCarousel } from "./ReplyCarousel";

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
 */
export function AssistantResponse({ response }: { response: ChatResponse }) {
  const agents = dedupeAgents(response);
  const followups = response.contributions.filter(
    (c) =>
      hasPendingQuestions(c.data ?? {}, c.agent) ||
      hasAssetAmountRequest(c.data ?? {}, c.agent),
  );

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

      {followups.length > 0 && (
        <div className="followup-block">
          <p className="followup-head">몇 가지만 더 확인할게요</p>
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
