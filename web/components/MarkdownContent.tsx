import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type MarkdownContentProps = {
  content: string;
  baseUrl?: string;
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

function resolveMarkdownUrl(baseUrl: string | undefined, value: string): string {
  const href = value.trim();
  if (!href) return href;
  if (!baseUrl) return href;
  if (/^(?:[a-z]+:)?\/\//i.test(href) || href.startsWith("data:") || href.startsWith("mailto:")) {
    return href;
  }

  try {
    return new URL(href, baseUrl).toString();
  } catch {
    return href;
  }
}

function isVideoUrl(url: string): boolean {
  return /\.(mp4|webm|ogg)(?:[?#].*)?$/i.test(url);
}

export function MarkdownContent({ content, baseUrl }: MarkdownContentProps) {
  return (
    <div className="message-text markdown-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ children, href, ...props }) => {
            const rawHref = typeof href === "string" ? href : "";
            const resolvedHref = resolveMarkdownUrl(baseUrl, rawHref);
            if (resolvedHref && isVideoUrl(resolvedHref)) {
              return (
                <video
                  className="markdown-video"
                  controls
                  preload="metadata"
                  src={resolvedHref}
                >
                  {children}
                </video>
              );
            }
            return (
              <a
                {...props}
                href={resolvedHref || rawHref || undefined}
                target="_blank"
                rel="noreferrer noopener"
              >
                {children}
              </a>
            );
          },
          img: ({ alt, src, ...props }) => {
            const rawSrc = typeof src === "string" ? src : "";
            const resolvedSrc = resolveMarkdownUrl(baseUrl, rawSrc);
            if (resolvedSrc && isVideoUrl(resolvedSrc)) {
              return (
                <video
                  className="markdown-video"
                  controls
                  preload="metadata"
                  src={resolvedSrc}
                  aria-label={alt || "video"}
                />
              );
            }
            return (
              <img
                {...props}
                alt={alt || ""}
                src={resolvedSrc || rawSrc || undefined}
                loading="lazy"
              />
            );
          },
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
