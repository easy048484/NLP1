import { Markdown } from "../../lib/markdown";
import type { ParsedConfirmChecklist } from "../../lib/replySections";

/**
 * decedent_estate가 "N가지만 직접 확인해주세요"로 여러 질문을 한 번에 몰아
 * 물을 때, 불릿 텍스트 대신 항목별 카드로 보여준다. 아직 구조화된
 * pending_questions(선택지 버튼)이 없는 자유 응답형 질문이라 답은 여전히
 * 직접 타이핑해야 한다 — 그래서 답변 예시를 한 줄 붙여 "어떻게 답해야
 * 할지" 막막함을 줄인다.
 */
export function ConfirmChecklistCard({ data }: { data: ParsedConfirmChecklist }) {
  const exampleLabel = data.items[0]?.label ?? "첫 번째 항목";

  return (
    <div className="confirm-checklist">
      <div className="confirm-checklist-intro">
        <Markdown>{data.intro}</Markdown>
      </div>

      <ul className="confirm-checklist-items">
        {data.items.map((item, i) => (
          <li key={i} className="confirm-checklist-item">
            <span className="confirm-checklist-icon" aria-hidden="true">
              ?
            </span>
            <div>
              <strong>{item.label}</strong>
              <p>{item.question}</p>
            </div>
          </li>
        ))}
      </ul>

      <p className="confirm-checklist-hint">
        아는 대로 편하게 답해 주세요. 예:{" "}
        <em>“{exampleLabel}는 맞고, 나머지는 잘 모르겠어요”</em>
      </p>

      {data.rest && (
        <div className="confirm-checklist-rest">
          <Markdown>{data.rest}</Markdown>
        </div>
      )}
    </div>
  );
}
