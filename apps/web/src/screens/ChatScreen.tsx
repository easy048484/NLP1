import { useState } from "react";
import { useApp } from "../lib/appState";
import { Composer } from "../components/chat/Composer";
import { FunctionRail } from "../components/chat/FunctionRail";
import { InstitutionWizard } from "../components/chat/InstitutionWizard";
import { MessageList } from "../components/chat/MessageList";
import { StarterPrompts } from "../components/chat/StarterPrompts";
import { Eyebrow } from "../components/ui";

export function ChatScreen() {
  const { turns, axis } = useApp();
  const [wizardOpen, setWizardOpen] = useState(false);

  const started = turns.length > 0 || wizardOpen;

  const title =
    axis === "post_death"
      ? "상속, 여기서부터 함께 정리해요"
      : axis === "pre_need"
        ? "미리 준비하는 상속, 무엇이 궁금하세요?"
        : "무엇을 도와드릴까요?";

  const lede =
    axis === "post_death"
      ? "지금 상황을 편하게 말씀해 주세요. 절차·재산·세금·분할을 순서대로 정리해 드리고, 전문가가 필요한 시점도 짚어 드립니다."
      : "지금 궁금한 것을 편하게 말씀해 주세요. 세금 시산·재산 정리·유언 준비를 필요한 만큼만 도와드립니다.";

  return (
    <div className="chat-screen">
      <div className={`fn-rail-head${started ? " compact" : ""}`}>
        <Eyebrow>AI 에이전트</Eyebrow>
        <h1>{title}</h1>
        <p className="fn-rail-lede">{lede}</p>

        {!started && <StarterPrompts />}

        {!started && <p className="fn-rail-or">또는, 기능으로 바로 시작</p>}
        <FunctionRail />

        {axis === "post_death" && !wizardOpen && (
          <button
            type="button"
            className="fn-rail-extra"
            onClick={() => setWizardOpen(true)}
          >
            안심상속 원스톱 조회결과부터 정리하기 →
          </button>
        )}
      </div>

      {started && (
        <MessageList>
          {wizardOpen && <InstitutionWizard onClose={() => setWizardOpen(false)} />}
        </MessageList>
      )}

      {!started && (
        <div className="chat-empty-hint">
          <p>
            예시 질문을 누르거나 아래에 직접 물어보시면 됩니다. 답변에 나온
            버튼을 누르면서 진행하시면 돼요.
          </p>
        </div>
      )}

      <Composer />
    </div>
  );
}
