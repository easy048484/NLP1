import { Button, Card } from "../ui";
import type { SuggestedAction } from "../../types";

/**
 * opt-in 후속 제안(SuggestedAction) 한 건 — 완료된 유언 요건 review 뒤에
 * "유류분 영향 확인하기" 같은 다음 상담을 제안한다. 자동 handoff가 아니라
 * 사용자가 이 버튼을 눌러야만 action.message가 새 user_message로 전송된다
 * (AssistantResponse가 useApp().send를 호출).
 *
 * followup-block(pending_questions 등 "답이 필요한" 블록)과 시각적으로
 * 구분하기 위해 골드 배경을 쓰지 않는다 — 이건 답을 강제하는 질문이 아니라
 * "원하면 눌러보라"는 참고용 제안이다.
 */
export function SuggestedActionCard({
  action,
  disabled = false,
  onSelect,
}: {
  action: SuggestedAction;
  /** 응답 대기 중(loading) 등 중복 클릭을 막아야 할 때 */
  disabled?: boolean;
  onSelect: () => void;
}) {
  return (
    <Card className="suggested-action-card">
      <p className="suggested-action-prompt">{action.prompt}</p>
      <Button onClick={onSelect} disabled={disabled}>
        {action.label}
      </Button>
    </Card>
  );
}
