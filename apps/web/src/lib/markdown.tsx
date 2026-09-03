import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * "**볼드**" 바로 뒤에 공백 없이 글자가 이어지면(조사가 명사에 바로 붙는
 * 한국어 문장 구조상 매우 흔함 — 예: "**안 날'**입니다") CommonMark의
 * 우측 플랭킹 규칙(닫는 델리미터가 구두점 뒤에 오면서 뒤따르는 문자가
 * 공백·구두점이 아니면 닫는 것으로 인정하지 않음)에 걸려 볼드로 파싱되지
 * 않고 별표가 그대로 노출된다. 닫는 "**" 뒤에 공백 하나를 끼워 넣어 항상
 * 파싱되게 한다 — 이미 공백/구두점이 뒤따르는 정상 케이스는 건드리지 않는다.
 */
function fixBoldClosingFlank(text: string): string {
  return text.replace(/\*\*([^\n*]+?)\*\*(?=[\p{L}\p{N}])/gu, "**$1** ");
}

/**
 * 백엔드 답변(마크다운-ish 평문)을 안전하게 렌더한다.
 *
 * 백엔드 `reply`는 `**굵게**`, `- 불릿`, `✅/❌/⚠️/📞/ℹ️` 이모지, `\n\n` 문단,
 * 때로 표를 포함한다. HTML은 허용하지 않고(기본값), 링크는 새 탭 + noopener.
 */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node, ...props }) => {
            void node;
            return <a {...props} target="_blank" rel="noopener noreferrer" />;
          },
        }}
      >
        {fixBoldClosingFlank(children)}
      </ReactMarkdown>
    </div>
  );
}
