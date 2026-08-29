import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type MarkdownContentProps = {
  content: string;
};

function normalizeSectionHeadings(content: string) {
  return content
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => {
      const standaloneBold = line.match(/^\s*\*\*\s*(.+?)\s*\*\*\s*$/);

      if (!standaloneBold) {
        return line;
      }

      return `## ${standaloneBold[1].trim()}`;
    })
    .join("\n")
    .trim();
}

export function MarkdownContent({ content }: MarkdownContentProps) {
  return (
    <div className="message-text markdown-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ children, ...props }) => (
            <a {...props} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          ),
          table: ({ children, ...props }) => (
            <div className="markdown-table-wrap">
              <table {...props}>{children}</table>
            </div>
          ),
        }}
      >
        {normalizeSectionHeadings(content)}
      </ReactMarkdown>
    </div>
  );
}
