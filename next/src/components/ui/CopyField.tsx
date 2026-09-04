"use client";

import { useEffect, useRef, useState } from "react";
import { FiCheck, FiCopy } from "react-icons/fi";
import { useTranslation } from "react-i18next";

/**
 * Поле «значение + копировать». Используется для адреса, суммы и memo.
 *
 * Копируется всегда СЫРОЕ значение (value), а не то, что нарисовано: сумма на
 * экране может быть с подписью монеты, а в кошелёк нужно вставить число.
 *
 * Запасной путь через невидимый textarea обязателен: в webview Telegram и
 * Instagram (а именно оттуда приходит половина людей) navigator.clipboard
 * часто недоступен, и без него кнопка молча ничего не делает.
 */
type Props = {
  label: string;
  value: string;
  display?: React.ReactNode;
  size?: "md" | "lg";
  tone?: "default" | "warning";
  className?: string;
};

export default function CopyField({
  label,
  value,
  display,
  size = "md",
  tone = "default",
  className = "",
}: Props) {
  const { t } = useTranslation("common");
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const copy = async () => {
    let done = false;
    try {
      await navigator.clipboard.writeText(value);
      done = true;
    } catch {
      done = false;
    }
    if (!done) {
      try {
        const area = document.createElement("textarea");
        area.value = value;
        area.setAttribute("readonly", "");
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        document.body.removeChild(area);
        done = true;
      } catch {
        done = false;
      }
    }
    if (!done) return;
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 2000);
  };

  const warning = tone === "warning";

  return (
    <div className={className}>
      <div className={`mb-1 text-xs ${warning ? "text-status-wait" : "text-muted"}`}>{label}</div>
      <div
        className={`flex items-start gap-2 rounded-xl border px-3 py-2.5 ${
          warning ? "border-status-wait/40 bg-status-wait/10" : "border-border bg-surface-2"
        }`}
      >
        <div
          className={`min-w-0 flex-1 select-all break-all font-mono text-foreground ${
            size === "lg" ? "text-2xl font-bold tabular-nums sm:text-3xl" : "text-[13px] leading-snug"
          }`}
        >
          {display ?? value}
        </div>
        <button
          type="button"
          onClick={() => void copy()}
          aria-label={label}
          title={t("crypto.copy", { defaultValue: "Копировать" })}
          className="shrink-0 rounded-lg border border-border p-2 text-muted transition-colors hover:border-accent hover:text-foreground cursor-pointer"
        >
          {copied ? <FiCheck className="text-status-ok" /> : <FiCopy />}
        </button>
      </div>
      <span aria-live="polite" className="sr-only">
        {copied ? t("crypto.copied", { defaultValue: "Скопировано" }) : ""}
      </span>
    </div>
  );
}
