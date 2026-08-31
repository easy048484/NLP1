import { useState } from "react";
import { useApp } from "../lib/appState";
import { Composer } from "../components/chat/Composer";
import { FunctionRail } from "../components/chat/FunctionRail";
import { InstitutionWizard } from "../components/chat/InstitutionWizard";
import { MessageList } from "../components/chat/MessageList";
import { Eyebrow } from "../components/ui";

export function ChatScreen() {
  const { turns, axis } = useApp();
  const [wizardOpen, setWizardOpen] = useState(false);

  const started = turns.length > 0 || wizardOpen;

  return (
    <div className="chat-screen">
      <div className={`fn-rail-head${started ? " compact" : ""}`}>
        <Eyebrow>AI 에이전트</Eyebrow>
        <h1>무엇을 도와드릴까요?</h1>
        <p className="fn-rail-lede">
          {axis === "post_death"
            ? "천천히 하셔도 됩니다. 필요한 기능을 고르시면 담당 에이전트가 단계별로 안내할게요."
            : "하고 싶은 일을 고르시면 담당 에이전트가 필요한 것만 순서대로 여쭤보고 정리해 드립니다."}
        </p>
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
            위에서 기능을 고르거나, 아래에 직접 물어보셔도 됩니다. 답변에 나온
            버튼을 누르면서 진행하시면 됩니다.
          </p>
        </div>
      )}

      <Composer />
    </div>
  );
}
