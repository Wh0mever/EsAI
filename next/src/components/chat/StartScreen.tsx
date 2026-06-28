"use client";

import { useTranslation } from "react-i18next";
import { QUICK_ACTIONS, SCENARIO_CARDS } from "./chatPresets";
import { presetIcon } from "./chatIcons";

type Props = {
  /** Inject a prompt template into the input (used by quick actions & cards). */
  onUsePrompt: (text: string) => void;
};

/**
 * StartScreen — the first screen of the chat: logo, slogan, quick actions and
 * scenario cards. Shown until the first message is sent.
 */
export default function StartScreen({ onUsePrompt }: Props) {
  const { t } = useTranslation("common");

  return (
    <div className="flex-1 flex flex-col items-center justify-center w-full max-w-3xl mx-auto px-1 py-6">
      {/* Brand + slogan */}
      <img src="/esai-logo.svg" alt="EsAI" className="h-10 sm:h-12 mb-5 select-none" />
      <h1 className="text-2xl sm:text-3xl font-semibold text-center text-foreground">
        {t("chat.start.greeting", { defaultValue: "Чем могу помочь?" })}
      </h1>
      <p className="mt-2 text-center text-muted">
        {t("brand.slogan", { defaultValue: "EsAI — Все нейросети в одном месте. Без лишних трат и подписок." })}
      </p>

      {/* Quick actions */}
      <div className="mt-7 flex flex-wrap justify-center gap-2">
        {QUICK_ACTIONS.map((qa) => (
          <button
            key={qa.id}
            type="button"
            onClick={() => onUsePrompt(t(qa.promptKey, { defaultValue: "" }))}
            className="inline-flex items-center gap-2 rounded-full border border-border bg-surface-2 hover:border-accent/60 hover:bg-surface-3 text-sm text-foreground px-3.5 py-2 transition-colors cursor-pointer"
          >
            <span className="text-accent text-base">{presetIcon(qa.iconKey)}</span>
            <span>{t(qa.labelKey, { defaultValue: qa.id })}</span>
          </button>
        ))}
      </div>

      {/* Scenario cards */}
      <div className="mt-8 w-full grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5">
        {SCENARIO_CARDS.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => onUsePrompt(t(c.promptKey, { defaultValue: "" }))}
            className="text-left rounded-xl border border-border bg-surface hover:border-accent/50 hover:bg-surface-2 p-3 transition-colors cursor-pointer group"
          >
            <span className="inline-flex items-center justify-center w-9 h-9 rounded-lg bg-accent-soft text-accent text-lg mb-2 group-hover:scale-105 transition-transform">
              {presetIcon(c.iconKey)}
            </span>
            <span className="block text-sm font-medium text-foreground leading-tight">
              {t(c.titleKey, { defaultValue: c.id })}
            </span>
            <span className="block text-xs text-muted mt-0.5 leading-snug line-clamp-2">
              {t(c.descKey, { defaultValue: "" })}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
