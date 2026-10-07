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
import { VS_FOCUS, vx } from "../ui/skin";
import { HINTS_VISIBLE, fixLabelKey, type HintItem } from "./composerLogic";
import { ct } from "./composerText";
import { HINT_BTN, HINT_BTN_PRIMARY, HINT_BTN_QUIET } from "./dockSkin";

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
      className={vx(HINT_BTN, primary ? HINT_BTN_PRIMARY : HINT_BTN_QUIET)}
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
    <li className="flex items-start gap-2.5 py-2">
      <Icon className={`mt-0.5 size-4 shrink-0 ${tone === "error" ? "text-status-fail" : "text-status-wait"}`} aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-3">
        <span className={`min-w-0 flex-1 text-[13px] leading-snug ${tone === "error" ? "text-foreground" : "text-muted"}`}>{text}</span>
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
    // Кромка — цвет статуса: красная, пока что-то мешает запуску, жёлтая — только предупреждения.
    <div
      className={vx("vs-card shrink-0 rounded-2xl px-3.5 py-0.5", hasErrors ? "!border-status-fail/40" : "!border-status-wait/35")}
      aria-live="polite"
    >
      {hasErrors && <h3 className="sr-only">{ct(t, "composer.errorsTitle")}</h3>}
      <ul className="flex flex-col divide-y divide-white/[0.07]">
        {shown.map((item, i) => (
          <HintRow key={`${item.issue.code}:${i}`} item={item} onFix={onFix} />
        ))}
      </ul>
      {(rest > 0 || expanded) && items.length > HINTS_VISIBLE && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className={vx(
            "flex min-h-9 cursor-pointer items-center gap-1 rounded-full text-xs font-medium text-muted transition-colors hover:text-foreground max-md:min-h-11",
            VS_FOCUS,
          )}
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
    <div className="vs-card flex shrink-0 flex-col gap-2 rounded-2xl px-3.5 py-2.5 sm:flex-row sm:items-center sm:gap-3" role="note">
      <FiFilm className="hidden size-4 shrink-0 text-accent sm:block" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-foreground">{ct(t, "meter.script.title")}</div>
        <div className="text-xs leading-snug text-muted">{ct(t, "meter.script.body")}</div>
      </div>
      <div className="flex shrink-0 flex-wrap gap-2">
        <Link
          href="/studio"
          className={vx(HINT_BTN, HINT_BTN_PRIMARY)}
        >
          {ct(t, "meter.script.cartoon")}
        </Link>
        <button
          type="button"
          onClick={onDismiss}
          className={vx(HINT_BTN, HINT_BTN_QUIET)}
        >
          {ct(t, "meter.script.anyway")}
        </button>
      </div>
    </div>
  );
}
