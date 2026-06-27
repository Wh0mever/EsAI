"use client";

import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ChatMode } from "@/types/chat";
import type { Message } from "./ChatForm";
import NextLink from "@/components/ui/nextLink/NextLink";
import { BACKEND } from "@/tools/fetchData";

/* ---------- utils ---------- */

function toAbsUrl(raw?: string): string {
  if (!raw) return "";
  if (raw.startsWith("/")) return `${BACKEND}${raw}`;
  return raw;
}

/* ---------- types ---------- */

type ChatViewProps = {
  messages: Message[];
  mode: ChatMode;
  loading?: boolean;
  initialHydrated?: boolean;
  animateIndex?: number | null;
};

type Attachment = {
  type?: string;
  url?: string;
  preview?: string;
  name?: string;
};

/* ---------- UI atoms ---------- */

function TypingText({
  text,
  speed = 18,
  onDone,
  className = "",
}: {
  text: string;
  speed?: number; // ms per char
  onDone?: () => void;
  className?: string;
}) {
  const [i, setI] = useState(0);
  const timerRef = useRef<number | null>(null);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    setI(0);
    if (!text) {
      onDone?.();
      return;
    }
    const tick = () => {
      setI((prev) => {
        const next = Math.min(prev + 1, text.length);
        if (next === text.length) {
          onDone?.();
          return next;
        }
        timerRef.current = window.setTimeout(tick, speed);
        return next;
      });
    };
    timerRef.current = window.setTimeout(tick, speed);
    return () => {
      cancelledRef.current = true;
      if (timerRef.current) window.clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, speed]);

  return <span className={className}>{text.slice(0, i)}</span>;
}

function ThinkingDots({ text = "Думаю" }: { text?: string }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setN((v) => (v + 1) % 4), 450);
    return () => window.clearInterval(id);
  }, []);
  return (
    <span aria-live="polite">
      {text}
      {".".repeat(n)}
    </span>
  );
}

/* ---------- micro components ---------- */

function EmptyState() {
  const { t } = useTranslation("common");
  return (
    <div className="flex-1 grid place-items-center min-h-[50vh]">
      <div className="text-center space-y-2">
        <h3 className="text-2xl text-white font-semibold">
          {t("chat.empty_text_title", { defaultValue: "Готов творить текст вместе с ESAI?" })}
        </h3>
        <p className="text-neutral-300">
          {t("chat.empty_text_subtitle", { defaultValue: "Тогда начнём!" })}
        </p>
      </div>
    </div>
  );
}

function AttachmentsList({ atts }: { atts?: Attachment[] }) {
  if (!Array.isArray(atts) || atts.length === 0) return null;
  return (
    <div className="mt-1 self-stretch">
      <div className="flex flex-wrap gap-2">
        {atts.map((a, i) => {
          const isImg = (a?.type || "").toLowerCase() === "image";
          const raw = a?.url || a?.preview || "";
          const url = toAbsUrl(raw);
          return (
            <div key={i} className="shrink-0">
              {isImg ? (
                <a href={url} target="_blank" rel="noreferrer">
                  <img
                    src={url}
                    alt={a?.name || "attachment"}
                    className="w-24 h-24 object-cover rounded-md border border-white/10"
                  />
                </a>
              ) : (
                <a
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  className="px-3 py-2 text-xs bg-neutral-800 hover:bg-neutral-700 rounded-md border border-white/10 inline-flex items-center gap-2"
                >
                  <span className="truncate max-w-[8rem]">{a?.name || "file"}</span>
                </a>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function BubbleContent({
  isUser,
  msg,
  isThinking,
  shouldType,
  onTypedDone,
}: {
  isUser: boolean;
  msg: Message;
  isThinking: boolean;
  shouldType: boolean;
  onTypedDone: () => void;
}) {
  const { t } = useTranslation("common");
  const extraLink = ((msg as any)?.link || "").toString().trim();
  const extraLinkLabel = ((msg as any)?.linkLabel || "").toString().trim();
  const extraLinkSecondary = ((msg as any)?.linkSecondary || "").toString().trim();
  const extraLinkSecondaryLabel = ((msg as any)?.linkSecondaryLabel || "").toString().trim();
  const isSystemNotice = !isUser && (msg as any)?.meta?.system_notice === "subscription";

  if (!isUser && isThinking) {
    return <ThinkingDots text={t("chat.thinking", { defaultValue: "Думаю" })} />;
  }

  if (!isUser && shouldType && msg.content) {
    return <TypingText text={msg.content} speed={18} onDone={onTypedDone} />;
  }

  if (!isUser && extraLink) {
    if (isSystemNotice) {
      return (
        <span className="flex flex-col items-center gap-2 text-center">
          <span>{msg?.content ?? t("chat.thinking_ellipsis", { defaultValue: "Думаю…" })}</span>
          <NextLink
            href={extraLink}
            className="inline-flex items-center justify-center rounded-md border border-rose-500 px-3 py-1 text-center text-rose-200 hover:bg-rose-500/10 hover:text-rose-100 cursor-pointer no-underline hover:no-underline"
          >
            {extraLinkLabel || t("chat.go_to_pricing", { defaultValue: "Перейти к тарифам" })}
          </NextLink>
          {extraLinkSecondary && (
            <NextLink
              href={extraLinkSecondary}
              className="inline-flex items-center justify-center rounded-md border border-rose-500/70 px-3 py-1 text-center text-rose-200 hover:bg-rose-500/10 hover:text-rose-100 cursor-pointer no-underline hover:no-underline"
            >
              {extraLinkSecondaryLabel || t("chat.go_to_pricing", { defaultValue: "Перейти к тарифам" })}
            </NextLink>
          )}
        </span>
      );
    }
    return (
      <span>
        {msg?.content ?? t("chat.thinking_ellipsis", { defaultValue: "Думаю…" })}{" "}
        <NextLink href={extraLink} className="underline underline-offset-2 text-sky-300 hover:text-sky-200 cursor-pointer">
          {extraLinkLabel || t("chat.go_to_pricing", { defaultValue: "Перейти к тарифам" })}
        </NextLink>
      </span>
    );
  }

  return <span>{msg?.content ?? t("chat.thinking_ellipsis", { defaultValue: "Думаю…" })}</span>;
}

function ChatBubble({
  msg,
  index,
  isLast,
  isThinking,
  shouldType,
  onTypedDone,
}: {
  msg: Message;
  index: number;
  isLast: boolean;
  isThinking: boolean;
  shouldType: boolean;
  onTypedDone: () => void;
}) {
  const isUser = msg.role === "user";
  const isError = !isUser && (msg as any)?.variant === "error";
  const isWarning = !isUser && (msg as any)?.variant === "warning";
  const isSystemNotice = !isUser && (msg as any)?.meta?.system_notice === "subscription";
  const visibleAttachments = (msg as any)?.attachments;

  const bubbleClass = isSystemNotice
    ? "self-center bg-neutral-800/70 border border-rose-500 text-neutral-100"
    : isUser
    ? "self-end bg-indigo-700 text-white"
    : isWarning
    ? "self-start bg-amber-700/90 border border-amber-400 text-white"
    : isError
    ? "self-start bg-rose-700/90 border border-rose-400 text-white"
    : "self-start bg-neutral-900 text-white";

  return (
    <div className={`flex flex-col gap-2 max-w-[80%] ${isSystemNotice ? "items-center self-center text-center" : "items-start"}`}>
      <div className={`p-4 rounded-xl whitespace-pre-wrap ${bubbleClass}`}>
        <BubbleContent
          isUser={isUser}
          msg={msg}
          isThinking={!isUser && isLast && isThinking}
          shouldType={shouldType}
          onTypedDone={onTypedDone}
        />
      </div>
      <AttachmentsList atts={visibleAttachments} />
    </div>
  );
}

/* ---------- list with animation logic ---------- */

function MessageList({
  messages,
  animateIndex,
  initialHydrated,
  onAfterType,
  isThinking,
  onScrollToBottom,
}: {
  messages: Message[];
  animateIndex?: number | null;
  initialHydrated?: boolean;
  onAfterType: (idx: number) => void;
  isThinking: boolean;
  onScrollToBottom: () => void;
}) {
  const animatedRef = useRef<Set<number>>(new Set());
  const hydrationDoneRef = useRef<boolean>(false);

  useEffect(() => {
    if (!initialHydrated || hydrationDoneRef.current) return;
    const set = animatedRef.current;
    for (let i = 0; i < messages.length; i++) {
      const m = messages[i];
      if (m?.role === "assistant" && m?.content) {
        if (typeof animateIndex === "number" && i === animateIndex) continue;
        set.add(i);
      }
    }
    hydrationDoneRef.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialHydrated, messages.length, animateIndex]);

  return (
    <>
      {messages.map((msg, index) => {
        const isUser = msg.role === "user";
        const isError = !isUser && (msg as any)?.variant === "error";

        const shouldType =
          !isUser &&
          !isError &&
          !!msg.content &&
          (!animatedRef.current.has(index) || (typeof animateIndex === "number" && index === animateIndex));

        return (
          <ChatBubble
            key={(msg as any)?.id != null ? `id-${(msg as any).id}` : `idx-${index}`}
            msg={msg}
            index={index}
            isLast={index === messages.length - 1}
            isThinking={isThinking}
            shouldType={shouldType}
            onTypedDone={() => {
              animatedRef.current.add(index);
              onAfterType(index);
              onScrollToBottom();
            }}
          />
        );
      })}
    </>
  );
}

/* ---------- main ---------- */

export function ChatView({
  messages,
  loading,
  initialHydrated,
  animateIndex,
}: ChatViewProps) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const { t } = useTranslation("common");
  const isEmpty = !messages || messages.length === 0;

  const last = messages[messages.length - 1];
  const isThinking =
    !messages.length ||
    (last?.role === "assistant" && (!last.content || last.content.trim() === ""));

  const stickToBottomRef = useRef<boolean>(true);

  const scrollToBottom = () => {
    const el = wrapRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  };

  useEffect(() => {
    if (stickToBottomRef.current) scrollToBottom();
  }, [messages.length]);

  const handleScroll = () => {
    const el = wrapRef.current;
    if (!el) return;
    const threshold = 64;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottomRef.current = distance <= threshold;
  };

  return (
    <div ref={wrapRef} onScroll={handleScroll} className="flex flex-col gap-4 overflow-y-auto pr-1">
      {isEmpty ? (
        <EmptyState />
      ) : (
        <MessageList
          messages={messages}
          animateIndex={animateIndex}
          initialHydrated={initialHydrated}
          isThinking={isThinking}
          onAfterType={() => {}}
          onScrollToBottom={() => {
            if (stickToBottomRef.current) scrollToBottom();
          }}
        />
      )}

      {messages.length > 0 && loading && last?.role === "user" && (
        <div className="p-4 rounded-xl max-w-[80%] whitespace-pre-wrap self-start bg-neutral-900 text-white">
          <ThinkingDots text={t("chat.thinking", { defaultValue: "Думаю" })} />
        </div>
      )}
    </div>
  );
}
