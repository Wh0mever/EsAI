"use client";

/**
 * Видеостудия, композер: что говорит компилятор (§4.7, §9.6).
 *
 * Над полем — ошибки (красные: из-за них «Создать» выключена) и
 * предупреждения (жёлтые: запуск разрешён) с кнопками исправления из fix:
 * «Сжать с ИИ», «Не учитывать», «Сделать первым кадром», «Применить 9:16»…
 * Текст — перевод по коду, русский бэкенда — defaultValue. Видно три, остальные
 * — «Ещё N». Отдельно — плашка «Похоже на сценарий» (§4.8).
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { FiAlertCircle, FiAlertTriangle, FiChevronDown, FiChevronUp, FiFilm } from "react-icons/fi";
import Link from "next/link";
import { issueFixes, issueText } from "@/lib/vstudio/errors";
import type { IssueFix } from "@/lib/vstudio/types";
import { HINTS_VISIBLE, fixLabelKey, type HintItem } from "./composerLogic";
import { ct } from "./composerText";

type T = ReturnType<typeof useTranslation>["t"];

/** Подпись кнопки исправления: «Применить 9:16», «Сжать с ИИ», «Оставить кадры»… */
export function fixLabel(t: T, fix: IssueFix): string {
  const key = fixLabelKey(fix);
  if (key === "fix.apply" && fix.action === "set_param") {
    const value = fix.value === "auto" ? ct(t, "imagegen.aspectAuto") : String(fix.value ?? "");
    return ct(t, key, { value });
  }
  return ct(t, key);
}

export function FixButton({ fix, onFix, primary }: { fix: IssueFix; onFix: (fix: IssueFix) => void; primary?: boolean }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  return (
    <button
      type="button"
      onClick={() => onFix(fix)}
      className={`inline-flex min-h-9 shrink-0 items-center rounded-lg px-2.5 text-xs font-semibold transition-colors max-md:min-h-11 cursor-pointer ${
        primary
          ? "bg-foreground text-background hover:opacity-90"
          : "border border-border bg-surface text-foreground hover:border-border-strong"
      }`}
    >
      {fixLabel(t, fix)}
    </button>
  );
}

function HintRow({ item, onFix }: { item: HintItem; onFix: (fix: IssueFix) => void }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { issue, tone } = item;
  const text = issueText(t, issue, tone === "error" ? "errors" : "warnings");
  const fixes = issueFixes(issue);
  const Icon = tone === "error" ? FiAlertCircle : FiAlertTriangle;
  return (
    <li className="flex items-start gap-2 py-1.5">
      <Icon className={`mt-0.5 size-4 shrink-0 ${tone === "error" ? "text-status-fail" : "text-status-wait"}`} aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:flex-row sm:items-start sm:gap-3">
        <span className={`min-w-0 flex-1 text-xs leading-snug ${tone === "error" ? "text-foreground" : "text-muted"}`}>{text}</span>
        {fixes.length > 0 && (
          <span className="flex shrink-0 flex-wrap gap-1.5">
            {fixes.map((fix, i) => (
              <FixButton key={`${fix.action}:${i}`} fix={fix} onFix={onFix} primary={tone === "error" && i === 0} />
            ))}
          </span>
        )}
      </div>
    </li>
  );
}

export type ComposerHintsProps = {
  items: HintItem[];
  onFix: (fix: IssueFix) => void;
};

export default function ComposerHints({ items, onFix }: ComposerHintsProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const [expanded, setExpanded] = useState(false);
  if (!items.length) return null;
  const hasErrors = items.some((i) => i.tone === "error");
  const shown = expanded ? items : items.slice(0, HINTS_VISIBLE);
  const rest = items.length - shown.length;
  return (
    <div
      className={`rounded-xl border px-3 py-1 ${hasErrors ? "border-status-fail/40 bg-status-fail/5" : "border-status-wait/40 bg-status-wait/5"}`}
      aria-live="polite"
    >
      {hasErrors && <h3 className="sr-only">{ct(t, "composer.errorsTitle")}</h3>}
      <ul className="flex flex-col divide-y divide-border/60">
        {shown.map((item, i) => (
          <HintRow key={`${item.issue.code}:${i}`} item={item} onFix={onFix} />
        ))}
      </ul>
      {(rest > 0 || expanded) && items.length > HINTS_VISIBLE && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex min-h-9 items-center gap-1 text-xs font-medium text-muted hover:text-foreground cursor-pointer"
          aria-expanded={expanded}
        >
          {expanded ? <FiChevronUp aria-hidden /> : <FiChevronDown aria-hidden />}
          {expanded ? ct(t, "composer.hintsLess") : ct(t, "composer.hintsMore", { n: rest })}
        </button>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* «Похоже на сценарий» (§4.8)                                        */
/* ------------------------------------------------------------------ */

export function ScriptBanner({ onDismiss }: { onDismiss: () => void }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface-2 px-3 py-2.5 sm:flex-row sm:items-center" role="note">
      <FiFilm className="hidden size-4 shrink-0 text-accent-strong sm:block" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-foreground">{ct(t, "meter.script.title")}</div>
        <div className="text-xs leading-snug text-muted">{ct(t, "meter.script.body")}</div>
      </div>
      <div className="flex shrink-0 flex-wrap gap-2">
        <Link
          href="/studio"
          className="inline-flex min-h-11 items-center rounded-xl bg-foreground px-3 text-xs font-semibold text-background hover:opacity-90 md:min-h-9"
        >
          {ct(t, "meter.script.cartoon")}
        </Link>
        <button
          type="button"
          onClick={onDismiss}
          className="inline-flex min-h-11 items-center rounded-xl border border-border bg-surface px-3 text-xs font-semibold text-foreground hover:border-border-strong md:min-h-9 cursor-pointer"
        >
          {ct(t, "meter.script.anyway")}
        </button>
      </div>
    </div>
  );
}
