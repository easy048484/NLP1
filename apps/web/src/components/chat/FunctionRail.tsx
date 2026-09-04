import { useApp } from "../../lib/appState";
import { AgentAvatar } from "../ui";
import type { AgentName } from "../../types";

/**
 * 에이전트가 제공하는 "기능" 타일. 대화창을 여는 대신, 하고 싶은 일을 고르면
 * 담당 에이전트가 그 작업을 단계별로 안내한다. 상담 화면 상단에 상시 노출.
 */
interface AgentFunction {
  key: string;
  agent: AgentName;
  name: string;
  blurb: string;
  prompt: string;
  axis?: "pre_need" | "post_death";
  /**
   * post_death 화면에서 쓸 문구 오버라이드 — axis를 지정하지 않고 두 화면
   * 모두에 노출하는 기능(예: asset_organizer)에서, 생전/사후 문구가 달라야
   * 할 때만 채운다.
   */
  postDeathBlurb?: string;
  postDeathPrompt?: string;
  /**
   * 클릭 시 현재 axis를 context.mode로 명시해서 보낼지 — asset_organizer처럼
   * 에이전트 자체가 pre_need/post_death 모드를 구분하는 경우에만 true.
   * (다른 기능들은 axis를 오케스트레이터 라우팅 힌트로만 쓰고 에이전트
   * 내부 모드 개념이 없어 해당 없음.)
   */
  sendModeContext?: boolean;
}

const AGENT_FUNCTIONS: AgentFunction[] = [
  {
    key: "asset",
    agent: "asset_organizer",
    name: "자산 정리",
    blurb: "예금·보험·부동산 등 재산과 부채를 한눈에 정리",
    prompt: "가진 재산과 부채를 미리 정리하고 싶어요",
    postDeathBlurb: "고인의 재산·부채와 안심상속 조회 결과를 한눈에 정리",
    postDeathPrompt: "돌아가신 가족의 재산과 부채를 정리하고 싶어요",
    sendModeContext: true,
  },
  {
    key: "will",
    agent: "decedent_estate",
    name: "유언 요건 점검",
    blurb: "유언장의 형식 요건을 판례에 비춰 항목별로 확인",
    prompt: "유언장 형식 요건을 점검하고 싶어요",
  },
  {
    key: "tax",
    agent: "tax_calculator",
    name: "상속세 시산",
    blurb: "재산·채무와 공제를 반영한 예상 세액을 단계별로",
    prompt: "상속세가 얼마나 나올지 계산해 주세요",
  },
  {
    key: "procedure",
    agent: "heir_navigator",
    name: "상속 절차 안내",
    blurb: "사망신고·기한·서류를 순서대로, 할 일 목록으로",
    prompt: "상속 절차를 처음부터 안내해 주세요",
    axis: "post_death",
  },
  {
    key: "share",
    agent: "heir_share_analyzer",
    name: "법정상속분 · 유류분",
    blurb: "누가 얼마를 받는지, 유류분 격차는 어느 정도인지",
    prompt: "법정상속분과 유류분을 계산해 주세요",
    axis: "post_death",
  },
];

export function FunctionRail() {
  const { turns, axis, send, loading } = useApp();

  const engaged = new Set(
    turns
      .filter((t) => t.role === "assistant" && t.response)
      .flatMap((t) => t.response!.contributions.map((c) => c.agent)),
  );

  const fns = AGENT_FUNCTIONS.filter((f) => !f.axis || f.axis === axis);
  const isPostDeath = axis === "post_death";

  return (
    <div className="fn-rail" role="group" aria-label="에이전트 기능">
      {fns.map((f) => {
        const active = engaged.has(f.agent);
        const blurb = isPostDeath && f.postDeathBlurb ? f.postDeathBlurb : f.blurb;
        const prompt = isPostDeath && f.postDeathPrompt ? f.postDeathPrompt : f.prompt;
        return (
          <button
            key={f.key}
            type="button"
            className={`fn-tile${active ? " fn-tile-active" : ""}`}
            disabled={loading}
            onClick={() =>
              void send(
                prompt,
                f.sendModeContext
                  ? { context: { mode: isPostDeath ? "post_death" : "pre_need" } }
                  : undefined,
              )
            }
          >
            <span className="fn-tile-top">
              <AgentAvatar agent={f.agent} size="sm" />
              {active && <span className="fn-tile-status">진행 중</span>}
            </span>
            <span className="fn-tile-name">{f.name}</span>
            <span className="fn-tile-blurb">{blurb}</span>
          </button>
        );
      })}
    </div>
  );
}
