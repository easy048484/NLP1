import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

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
        {children}
      </ReactMarkdown>
    </div>
  );
}
