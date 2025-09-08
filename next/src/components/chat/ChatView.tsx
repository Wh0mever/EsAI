"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Message } from "./ChatForm";

type ChatViewProps = { messages: Message[] };

// types text char-by-char on mount
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
  useEffect(() => {
    if (!text) {
      onDone?.();
      return;
    }
    let cancelled = false;
    const tick = () => {
      setI((v) => {
        const nv = Math.min(v + 1, text.length);
        if (nv === text.length) onDone?.();
        return nv;
      });
      if (!cancelled && i + 1 < text.length) {
        timer = window.setTimeout(tick, speed);
      }
    };
    let timer = window.setTimeout(tick, speed);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, speed]);
  return <span className={className}>{text.slice(0, i)}</span>;
}

// animated "Thinking..." placeholder
function ThinkingDots({ text = "Думаю" }: { text?: string }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setN((v) => (v + 1) % 4), 450);
    return () => clearInterval(id);
  }, []);
  return (
    <span aria-live="polite">
      {text}
      {".".repeat(n)}
    </span>
  );
}

export function ChatView({ messages }: ChatViewProps) {
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // detect "thinking": last assistant message is missing or empty
  const last = messages[messages.length - 1];
  const isThinking =
    !messages.length ||
    (last?.role === "assistant" && (!last.content || last.content.trim() === ""));

  // remember which message indices already animated
  const animatedRef = useRef<Set<number>>(new Set());

  // autoscroll to bottom on new messages / during typing
  const scrollToBottom = () => {
    const el = wrapRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  };
  useEffect(() => {
    scrollToBottom();
  }, [messages.length]);

  return (
    <div
      ref={wrapRef}
      className="flex flex-col gap-4 overflow-y-auto max-h-[calc(100vh-300px)] pr-1"
    >
      {messages.map((msg, index) => {
        const isUser = msg.role === "user";
        const bubbleClass = isUser
          ? "self-end bg-indigo-700 text-white"
          : "self-start bg-neutral-900 text-white";

        const shouldType =
          // only assistants
          !isUser &&
          // only if content exists
          !!msg.content &&
          // only if not typed before
          !animatedRef.current.has(index);

        return (
          <div
            key={index}
            className={`p-4 rounded-xl max-w-[80%] whitespace-pre-wrap ${bubbleClass}`}
          >
            {/* thinking placeholder for the last assistant message with no content */}
            {!isUser && index === messages.length - 1 && isThinking ? (
              <ThinkingDots />
            ) : shouldType ? (
              <TypingText
                text={msg.content}
                speed={18}
                onDone={() => {
                  animatedRef.current.add(index);
                  // keep view pinned to bottom while finishing typing
                  scrollToBottom();
                }}
              />
            ) : (
              <span>{msg?.content ?? "Думаю…"}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
