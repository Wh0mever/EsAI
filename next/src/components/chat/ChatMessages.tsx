"use client";

import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Markdown from "./Markdown";
import MessageActions from "./MessageActions";
import NextLink from "@/components/ui/nextLink/NextLink";
import { BACKEND } from "@/tools/fetchData";
import type { Message, ChatSource } from "@/types/chat";

function toAbsUrl(raw?: string): string {
  if (!raw) return "";
  return raw.startsWith("/") ? `${BACKEND}${raw}` : raw;
}

/* ---------- typing effect (streaming-ready) ---------- */
function useTyping(text: string, enabled: boolean, onTick: () => void) {
  const [count, setCount] = useState(enabled ? 0 : text.length);
  const doneRef = useRef(!enabled);

  useEffect(() => {
    if (!enabled) {
      setCount(text.length);
      doneRef.current = true;
      return;
    }
    setCount(0);
    doneRef.current = false;
    let i = 0;
    // chunk a few chars per tick so long answers don't crawl
    const step = Math.max(1, Math.round(text.length / 600));
    const id = window.setInterval(() => {
      i = Math.min(i + step, text.length);
      setCount(i);
      onTick();
      if (i >= text.length) {
        doneRef.current = true;
        window.clearInterval(id);
      }
    }, 16);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, enabled]);

  return { shown: text.slice(0, count), done: doneRef.current || count >= text.length };
}

function ThinkingDots() {
  const { t } = useTranslation("common");
  const [n, setN] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setN((v) => (v + 1) % 4), 400);
    return () => window.clearInterval(id);
  }, []);
  return (
    <span className="text-muted" aria-live="polite">
      {t("chat.thinking", { defaultValue: "Думаю" })}
      {".".repeat(n)}
    </span>
  );
}

function Attachments({ atts }: { atts?: any[] }) {
  if (!Array.isArray(atts) || atts.length === 0) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-2">
      {atts.map((a, i) => {
        const isImg = (a?.type || "").toLowerCase() === "image";
        const url = toAbsUrl(a?.url || a?.preview || "");
        return isImg ? (
          <a key={i} href={url} target="_blank" rel="noreferrer">
            <img src={url} alt={a?.name || "attachment"} className="w-24 h-24 object-cover rounded-lg border border-border" />
          </a>
        ) : (
          <a
            key={i}
            href={url}
            target="_blank"
            rel="noreferrer"
            className="px-3 py-2 text-xs bg-surface-2 hover:bg-surface-3 rounded-lg border border-border inline-flex items-center gap-2"
          >
            <span className="truncate max-w-[8rem]">{a?.name || "file"}</span>
          </a>
        );
      })}
    </div>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function Sources({ sources }: { sources?: ChatSource[] }) {
  const { t } = useTranslation("common");
  if (!Array.isArray(sources) || sources.length === 0) return null;
  const clean = sources.filter((s) => s && s.url);
  if (clean.length === 0) return null;
  return (
    <div className="mt-2 rounded-xl border border-border bg-surface-2/60 px-3 py-2.5">
      <p className="text-xs font-semibold text-muted mb-1.5">
        {t("chat.sources", { defaultValue: "Источники" })}
      </p>
      <ol className="flex flex-col gap-1">
        {clean.map((s, i) => (
          <li key={`${s.url}-${i}`} className="text-sm leading-snug flex gap-2">
            <span className="text-muted-2 shrink-0 tabular-nums">{i + 1}.</span>
            <a
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent-strong hover:underline underline-offset-2 break-words min-w-0"
              title={s.url}
            >
              <span>{s.title?.trim() || hostOf(s.url)}</span>
              <span className="text-muted-2 text-xs ml-1">({hostOf(s.url)})</span>
            </a>
          </li>
        ))}
      </ol>
    </div>
  );
}

function AssistantBubble({
  msg,
  animate,
  onScroll,
  onRetry,
  onContinue,
  onFeedback,
}: {
  msg: Message;
  animate: boolean;
  onScroll: () => void;
  onRetry?: () => void;
  onContinue?: () => void;
  onFeedback?: (v: "up" | "down") => void;
}) {
  const { t } = useTranslation("common");
  const content = msg.content || "";
  const streaming = (msg as any)?.streaming === true;
  // Typing-effect only on the non-stream fallback path. While streaming, real
  // deltas drive the text, so we render `content` directly.
  const { shown, done: typedDone } = useTyping(content, animate && !streaming, onScroll);

  const isError = (msg as any)?.variant === "error";
  const isWarning = (msg as any)?.variant === "warning";
  const link = ((msg as any)?.link || "").toString().trim();
  const linkLabel = ((msg as any)?.linkLabel || "").toString().trim();
  const sources = (msg as any)?.sources as ChatSource[] | undefined;

  // Keep the view pinned to the bottom as streamed text grows.
  useEffect(() => {
    if (streaming) onScroll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, streaming]);

  const text = streaming ? content : shown;
  const showCaret = streaming || (!typedDone && animate);
  const finished = !streaming && (typedDone || !animate);

  const tone = isError
    ? "border border-rose-500/40 bg-rose-500/10"
    : isWarning
    ? "border border-amber-500/40 bg-amber-500/10"
    : "bg-bubble-assistant border border-border";

  return (
    <div className="flex flex-col gap-1 max-w-[88%] sm:max-w-[80%] self-start">
      <div className={`px-4 py-3 rounded-2xl rounded-tl-md text-foreground ${tone}`}>
        {isError || isWarning ? (
          <span className="whitespace-pre-wrap">{content}</span>
        ) : streaming && !text ? (
          <ThinkingDots />
        ) : (
          <span className={showCaret ? "esai-caret" : ""}>
            <Markdown content={text} />
          </span>
        )}
        {link && (
          <div className="mt-2">
            <NextLink href={link} className="text-accent-strong underline underline-offset-2 cursor-pointer">
              {linkLabel || t("chat.go_to_pricing", { defaultValue: "Перейти к тарифам" })}
            </NextLink>
          </div>
        )}
        {!isError && !isWarning && <Sources sources={sources} />}
      </div>
      {!isError && !isWarning && finished && content && (
        <MessageActions content={content} onRetry={onRetry} onContinue={onContinue} onFeedback={onFeedback} />
      )}
    </div>
  );
}

function UserBubble({ msg }: { msg: Message }) {
  return (
    <div className="flex flex-col gap-1 max-w-[88%] sm:max-w-[80%] self-end items-end">
      <div className="px-4 py-3 rounded-2xl rounded-tr-md bg-bubble-user border border-border text-foreground whitespace-pre-wrap">
        {msg.content}
      </div>
      <Attachments atts={(msg as any)?.attachments} />
    </div>
  );
}

type Props = {
  messages: Message[];
  loading: boolean;
  animateIndex?: number | null;
  onRetry?: () => void;
  onContinue?: () => void;
  onFeedback?: (index: number, v: "up" | "down") => void;
};

export default function ChatMessages({ messages, loading, animateIndex, onRetry, onContinue, onFeedback }: Props) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const stick = useRef(true);

  const scrollToBottom = () => {
    const el = wrapRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  };

  useEffect(() => {
    if (stick.current) scrollToBottom();
  }, [messages.length, loading]);

  const onScroll = () => {
    const el = wrapRef.current;
    if (!el) return;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight <= 80;
  };

  const last = messages[messages.length - 1];
  const showThinking = loading && last?.role === "user";

  return (
    <div ref={wrapRef} onScroll={onScroll} className="flex-1 overflow-y-auto">
      <div className="flex flex-col gap-4 w-full max-w-3xl mx-auto px-1 py-4">
        {messages.map((msg, i) =>
          msg.role === "user" ? (
            <UserBubble key={(msg as any)?.id != null ? `id-${(msg as any).id}` : `u-${i}`} msg={msg} />
          ) : (
            <AssistantBubble
              key={(msg as any)?.id != null ? `id-${(msg as any).id}` : `a-${i}`}
              msg={msg}
              animate={typeof animateIndex === "number" && i === animateIndex}
              onScroll={() => {
                if (stick.current) scrollToBottom();
              }}
              onRetry={i === messages.length - 1 ? onRetry : undefined}
              onContinue={i === messages.length - 1 ? onContinue : undefined}
              onFeedback={(v) => onFeedback?.(i, v)}
            />
          )
        )}
        {showThinking && (
          <div className="px-4 py-3 rounded-2xl rounded-tl-md bg-bubble-assistant border border-border max-w-[80%] self-start">
            <ThinkingDots />
          </div>
        )}
      </div>
    </div>
  );
}
