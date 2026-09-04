import { useApp } from "../../lib/appState";
import type { ConsultAxis } from "../../types";

/**
 * 상담 화면 첫 진입 시 "무엇을 물어볼 수 있는지" 를 예시 질문으로 보여줘
 * 사용자의 첫 행동을 이끈다. 클릭하면 그 문장이 그대로 전송된다.
 *
 * 기능 타일(FunctionRail)은 "기능"을 고르는 방식이라 처음 온 사람에게는
 * 막연하다 — 실제 사람이 칠 법한 문장을 먼저 보여준다. 사후/생전은 첫
 * 고민이 완전히 다르므로 예시도 분리한다.
 */
const STARTERS: Record<ConsultAxis, { label: string; prompt: string }[]> = {
  post_death: [
    {
      label: "아버지가 얼마 전에 돌아가셨어요. 뭐부터 해야 하나요?",
      prompt: "아버지가 얼마 전에 돌아가셨어요. 뭐부터 해야 할지 모르겠어요.",
    },
    {
      label: "안심상속 조회 결과를 정리하고 싶어요",
      prompt:
        "안심상속 원스톱으로 조회했어요. 나온 재산·부채를 정리하고 싶어요.",
    },
    {
      label: "빚이 있을까 걱정인데, 상속을 포기해야 하나요?",
      prompt: "빚이 더 있을까 봐 걱정돼요. 상속을 포기해야 하나요?",
    },
    {
      label: "상속세가 얼마나 나올까요?",
      prompt: "상속세가 얼마나 나올지 궁금해요.",
    },
    {
      label: "형제끼리 어떻게 나눠야 하나요?",
      prompt: "형제끼리 상속재산을 어떻게 나눠야 하는지 모르겠어요.",
    },
  ],
  pre_need: [
    {
      label: "제가 죽으면 자식들이 상속세를 얼마나 낼까요?",
      prompt: "제가 죽으면 자녀가 상속세를 얼마나 내야 할지 궁금해요.",
    },
    {
      label: "가진 재산을 미리 정리해 두고 싶어요",
      prompt: "가진 재산을 미리 정리해 두고 싶어요.",
    },
    {
      label: "유언장을 남기려면 뭘 준비해야 하나요?",
      prompt: "유언장을 남기려고 하는데 뭘 준비해야 하는지 알려주세요.",
    },
    {
      label: "특정 자녀에게 더 물려주고 싶은데 괜찮을까요?",
      prompt:
        "특정 자녀에게 재산을 더 물려주고 싶은데, 나중에 문제가 될까요?",
    },
  ],
};

export function StarterPrompts() {
  const { axis, send, loading } = useApp();
  const items = STARTERS[axis ?? "post_death"];

  return (
    <div className="starter-prompts">
      <p className="starter-prompts-label">
        {axis === "pre_need"
          ? "이런 걸 물어보실 수 있어요"
          : "이렇게 시작해 보세요"}
      </p>
      <div className="starter-prompts-list" role="group" aria-label="예시 질문">
        {items.map((s) => (
          <button
            key={s.label}
            type="button"
            className="starter-chip"
            disabled={loading}
            onClick={() => void send(s.prompt)}
          >
            {s.label}
          </button>
        ))}
      </div>
    </div>
  );
}
