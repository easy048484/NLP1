import { agentMeta } from "../../lib/agents";
import { Markdown } from "../../lib/markdown";
import type { ChatResponse } from "../../types";
import { hasPendingQuestions } from "../../lib/agentData";
import { AgentAvatar, ConcatNoticeBadge, NeedsReviewBadge } from "../ui";
import { AgentCards } from "./AgentCards";

/**
 * 합성(compose) 응답 한 건.
 * - 응답한 에이전트 아이덴티티 헤더 (아바타 + 이름)
 * - needs_review 배지
 * - 본문 마크다운 (서술만) — 담당 에이전트색 좌측 라인
 * - 기여별 근거 카드
 */
export function AssistantResponse({ response }: { response: ChatResponse }) {
  const agents = dedupeAgents(response);
  const followups = response.contributions.filter((c) =>
    hasPendingQuestions(c.data ?? {}, c.agent),
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
        <div className="assistant-bubble">
          <Markdown>{response.reply}</Markdown>
        </div>
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
