"use client";

import { memo, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { slugify } from "@/lib/content";

/** Flatten React children to plain text (for heading slug ids). */
function childrenToText(children: ReactNode): string {
  if (children == null) return "";
  if (typeof children === "string" || typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(childrenToText).join("");
  if (typeof children === "object" && "props" in (children as any)) {
    return childrenToText((children as any).props?.children);
  }
  return "";
}

/**
 * Renders article Markdown with the SAME slug ids that `extractToc` produces,
 * so the table-of-contents anchors resolve. Uses a per-render de-dup counter
 * that mirrors `extractToc`'s `id`, `id-1`, `id-2` scheme.
 */
function ArticleContentImpl({ content }: { content: string }) {
  const seen = new Map<string, number>();
  const headingId = (children: ReactNode): string => {
    const base = slugify(childrenToText(children)) || "section";
    const n = seen.get(base) || 0;
    seen.set(base, n + 1);
    return n > 0 ? `${base}-${n}` : base;
  };

  return (
    <div className="esai-md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          h2: ({ children }) => <h2 id={headingId(children)}>{children}</h2>,
          h3: ({ children }) => <h3 id={headingId(children)}>{children}</h3>,
          a: ({ href, children }) => {
            const internal = typeof href === "string" && href.startsWith("/");
            const anchor = typeof href === "string" && href.startsWith("#");
            return (
              <a
                href={href}
                {...(internal || anchor ? {} : { target: "_blank", rel: "noopener noreferrer" })}
              >
                {children}
              </a>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export const ArticleContent = memo(ArticleContentImpl);
export default ArticleContent;
