"use client";

import { memo, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { FiCopy, FiCheck } from "react-icons/fi";
import { useTranslation } from "react-i18next";

/** Extract plain text from arbitrary React children (for copy). */
function childrenToText(children: ReactNode): string {
  if (children == null) return "";
  if (typeof children === "string" || typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(childrenToText).join("");
  if (typeof children === "object" && "props" in (children as any)) {
    return childrenToText((children as any).props?.children);
  }
  return "";
}

function CodeBlock({ children }: { children: ReactNode }) {
  const { t } = useTranslation("common");
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(childrenToText(children));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  };

  return (
    <div className="relative group">
      <button
        type="button"
        onClick={copy}
        className="absolute top-2 right-2 z-10 inline-flex items-center gap-1 rounded-md bg-black/40 hover:bg-black/60 text-neutral-200 text-xs px-2 py-1 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
        title={t("chat.actions.copy", { defaultValue: "Копировать" })}
      >
        {copied ? <FiCheck /> : <FiCopy />}
        <span>{copied ? t("chat.actions.copied", { defaultValue: "Скопировано" }) : t("chat.actions.copy", { defaultValue: "Копировать" })}</span>
      </button>
      {/* text-neutral-200 обязателен: фон .esai-md pre всегда тёмный (#0d1117,
          globals.css), но у фенса БЕЗ языка rehype-highlight не вешает класс
          .hljs, и цвет текста наследуется от пузыря — в светлой теме это почти
          чёрный #141414 на почти чёрном фоне (контраст ~1.1:1, код не виден).
          Для блоков с языком .hljs на <code> перебивает это правило, так что
          подсветка синтаксиса не ломается. */}
      <pre className="text-neutral-200">{children}</pre>
    </div>
  );
}

function MarkdownImpl({ content }: { content: string }) {
  return (
    <div className="esai-md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          // Wrap top-level <pre> with a copy button.
          pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
          // Open links in a new tab safely.
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export const Markdown = memo(MarkdownImpl);
export default Markdown;
