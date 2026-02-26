"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { BACKEND } from "@/tools/fetchData";
import { useTranslation } from "react-i18next";
import type { ChatMode } from "@/types/chat";
import type { Message } from "./ChatForm";

/* ---------- utils ---------- */

function isImageUrl(s: string): boolean {
  if (!s) return false;
  const lower = s.toLowerCase();
  if (lower.startsWith("/media/generated/") || lower.includes("/generated/")) return true;
  return /\.(png|jpe?g|webp|gif)(\?.*)?$/.test(lower);
}

function isAudioUrl(s: string): boolean {
  if (!s) return false;
  const lower = s.toLowerCase();
  return /\.(mp3|wav|ogg|m4a|aac|flac)(\?.*)?$/.test(lower);
}

function extractAudioUrl(raw: string): string {
  const value = (raw || "").trim();
  if (!value) return "";
  if (isAudioUrl(value)) return value;

  const urlMatch = value.match(/https?:\/\/[^\s"'<>]+/gi);
  if (urlMatch) {
    const firstAudio = urlMatch.find((u) => isAudioUrl(u));
    if (firstAudio) return firstAudio;
  }

  try {
    const parsed = JSON.parse(value);
    const queue: any[] = [parsed];
    while (queue.length) {
      const current = queue.shift();
      if (!current) continue;
      if (typeof current === "string" && isAudioUrl(current)) return current;
      if (Array.isArray(current)) {
        queue.push(...current);
      } else if (typeof current === "object") {
        queue.push(...Object.values(current));
      }
    }
  } catch {}

  return "";
}

function toAbsUrl(raw?: string): string {
  if (!raw) return "";
  return raw.startsWith("/") ? `${BACKEND}${raw}` : raw;
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

function EmptyState({ mode }: { mode: ChatMode }) {
  const { t } = useTranslation("common");
  const isText = mode === "text-chat";
  const isMusic = mode === "music-chat";
  return (
    <div className="flex-1 grid place-items-center min-h-[50vh]">
      <div className="text-center space-y-2">
        <h3 className="text-2xl text-white font-semibold">
          {isText
            ? t("chat.empty_text_title", { defaultValue: "Готов творить текст вместе с Vokalo?" })
            : isMusic
            ? t("chat.empty_music_title", { defaultValue: "Готов создавать музыку вместе с Vokalo?" })
            : t("chat.empty_image_title", { defaultValue: "Готов создавать изображения вместе с Vokalo?" })}
        </h3>
        <p className="text-neutral-300">
          {isText
            ? t("chat.empty_text_subtitle", { defaultValue: "Тогда начнём!" })
            : isMusic
            ? t("chat.empty_music_subtitle", { defaultValue: "Тогда начнём!" })
            : t("chat.empty_image_subtitle", { defaultValue: "Тогда начнём!" })}
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
          const isAudio = ["audio", "music", "audio_file"].includes((a?.type || "").toLowerCase());
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
              ) : isAudio ? (
                <div className="w-64 p-2 rounded-md border border-white/10 bg-neutral-900">
                  <audio controls preload="none" src={url} className="w-full" />
                </div>
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
  const audioUrl = !isUser ? extractAudioUrl(msg.content || "") : "";

  if (!isUser && msg.content && isImageUrl(msg.content)) {
    const src = toAbsUrl(msg.content);
    return <img src={src} alt="generated" className="max-w-full rounded-lg" />;
  }

  if (!isUser && audioUrl) {
    const src = toAbsUrl(audioUrl);
    return (
      <div className="flex flex-col gap-2 min-w-[16rem]">
        <audio controls preload="none" src={src} className="w-full" />
        <a href={src} target="_blank" rel="noreferrer" className="text-xs underline underline-offset-2">
          {t("chat.download", { defaultValue: "Скачать" })}
        </a>
      </div>
    );
  }

  if (!isUser && isThinking) {
    return <ThinkingDots text={t("chat.thinking", { defaultValue: "Думаю" })} />;
  }

  if (!isUser && shouldType && msg.content) {
    return <TypingText text={msg.content} speed={18} onDone={onTypedDone} />;
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

  const bubbleClass = isUser
    ? "self-end bg-indigo-700 text-white"
    : isError
    ? "self-start bg-rose-700/90 border border-rose-400 text-white"
    : "self-start bg-neutral-900 text-white";

  return (
    <div className="flex flex-col items-start gap-2 max-w-[80%]">
      <div className={`p-4 rounded-xl whitespace-pre-wrap ${bubbleClass}`}>
        <BubbleContent
          isUser={isUser}
          msg={msg}
          isThinking={!isUser && isLast && isThinking}
          shouldType={shouldType}
          onTypedDone={onTypedDone}
        />
      </div>
      <AttachmentsList atts={(msg as any)?.attachments} />
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
  mode,
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
        <EmptyState mode={mode} />
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
