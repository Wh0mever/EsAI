"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { FiCopy, FiCheck, FiRefreshCw, FiCornerDownRight, FiThumbsUp, FiThumbsDown } from "react-icons/fi";

type Props = {
  content: string;
  onRetry?: () => void;
  onContinue?: () => void;
  onFeedback?: (value: "up" | "down") => void;
};

/** Action row shown under each assistant answer. */
export default function MessageActions({ content, onRetry, onContinue, onFeedback }: Props) {
  const { t } = useTranslation("common");
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState<"up" | "down" | null>(null);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content || "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  };

  const sendFeedback = (v: "up" | "down") => {
    setFeedback(v);
    onFeedback?.(v);
  };

  const btn =
    "inline-flex items-center justify-center w-8 h-8 rounded-lg text-muted hover:text-foreground hover:bg-surface-2 transition-colors cursor-pointer";

  return (
    <div className="flex items-center gap-1 mt-1.5 -ml-1">
      <button type="button" className={btn} onClick={copy} title={t("chat.actions.copy", { defaultValue: "Копировать" })}>
        {copied ? <FiCheck className="text-accent" /> : <FiCopy />}
      </button>
      {onRetry && (
        <button type="button" className={btn} onClick={onRetry} title={t("chat.actions.retry", { defaultValue: "Повторить" })}>
          <FiRefreshCw />
        </button>
      )}
      {onContinue && (
        <button type="button" className={btn} onClick={onContinue} title={t("chat.actions.continue", { defaultValue: "Продолжить" })}>
          <FiCornerDownRight />
        </button>
      )}
      <button
        type="button"
        className={`${btn} ${feedback === "up" ? "text-accent" : ""}`}
        onClick={() => sendFeedback("up")}
        title={t("chat.actions.like", { defaultValue: "Хороший ответ" })}
      >
        <FiThumbsUp />
      </button>
      <button
        type="button"
        className={`${btn} ${feedback === "down" ? "text-accent" : ""}`}
        onClick={() => sendFeedback("down")}
        title={t("chat.actions.dislike", { defaultValue: "Плохой ответ" })}
      >
        <FiThumbsDown />
      </button>
    </div>
  );
}
