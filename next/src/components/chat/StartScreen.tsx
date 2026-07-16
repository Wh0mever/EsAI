"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import Link from "next/link";
import { FiFilm, FiArrowRight } from "react-icons/fi";
import EsaiLogo from "@/components/brand/EsaiLogo";

type Props = {
  /** Inject a prompt template into the input (used by quick actions & cards). */
  onUsePrompt: (text: string) => void;
  /**
   * Композер чата (поле ввода) — рендерится СРАЗУ под слоганом, чтобы поле
   * ввода было видно без прокрутки (ТЗ клиента: «чат вверх»). Быстрые действия
   * и сценарии показываются ниже.
   */
  composerSlot?: ReactNode;
  /** Открыта экранная клавиатура (мобайл) — прижимаем контент к верху, без провала. */
  keyboardOpen?: boolean;
};

/**
 * StartScreen — the first screen of the chat: logo, slogan, the chat input
 * (right under the slogan) and the /studio banner. Shown until the first
 * message is sent. Scrolls internally on small screens so the input stays
 * above the fold.
 *
 * The old quick-actions pills + scenario cards grid was removed: that
 * functionality is superseded by the new 8-section marketing landing
 * (see next/src/app/(home)/page.tsx — HomeHero and siblings), which now
 * carries the "what can EsAI do" pitch instead of this in-chat block.
 */
export default function StartScreen({ onUsePrompt, composerSlot, keyboardOpen }: Props) {
  const { t } = useTranslation("common");

  return (
    <div className="flex-1 min-h-0 overflow-y-auto w-full">
      <div
        className={
          "max-w-3xl mx-auto w-full min-h-full flex flex-col px-1 " +
          // При открытой клавиатуре прижимаем к верху (композер сразу под слоганом,
          // без пустого провала снизу); иначе — центрируем для красоты.
          (keyboardOpen ? "justify-start py-3" : "justify-center py-5")
        }
      >
        {/* Brand + slogan */}
        <div className="flex flex-col items-center">
          <EsaiLogo className="h-9 sm:h-11 mb-4 select-none w-auto" />
          {/* Слоган — вверху и крупно (главный акцент), приветствие — ниже и мельче. */}
          <h1 className="text-2xl sm:text-3xl font-semibold text-center text-foreground text-balance">
            {t("brand.slogan", { defaultValue: "EsAI — Все нейросети в одном месте. Без лишних трат и подписок." })}
          </h1>
          <p className="mt-2 text-center text-muted">
            {t("chat.start.greeting", { defaultValue: "Чем могу помочь?" })}
          </p>
        </div>

        {/* Композер сразу под слоганом — пользователь начинает печатать без прокрутки */}
        {composerSlot ? <div className="w-full mt-5">{composerSlot}</div> : null}

        {/* Флагман-баннер: «Создание мультфильмов» → студия /studio. Крупная,
            заметная карточка-ссылка (не подстановка промпта, а переход). */}
        <Link
          href="/studio"
          className="group mt-5 w-full flex items-center gap-4 rounded-2xl border border-accent/40 bg-accent-soft px-4 py-4 sm:px-5 sm:py-5 hover:border-accent transition-colors cursor-pointer"
        >
          <span className="grid h-12 w-12 sm:h-14 sm:w-14 shrink-0 place-items-center rounded-2xl bg-surface text-2xl sm:text-3xl">
            🎬
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-2">
              <span className="text-base sm:text-lg font-bold text-foreground">
                {t("chat.start.studio_title", { defaultValue: "Создание мультфильмов" })}
              </span>
              <span className="shrink-0 rounded-full bg-accent px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-on-accent">
                {t("common.new_badge", { defaultValue: "Новинка" })}
              </span>
            </span>
            <span className="mt-0.5 block text-sm text-muted leading-snug">
              {t("chat.start.studio_desc", {
                defaultValue: "Придумайте историю, нарисуйте героев и оживите их в видео — без навыков.",
              })}
            </span>
          </span>
          <FiFilm className="hidden sm:block shrink-0 text-2xl text-accent" />
          <FiArrowRight className="shrink-0 text-xl text-accent transition-transform group-hover:translate-x-0.5" />
        </Link>
      </div>
    </div>
  );
}
