"use client";

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import Link from "next/link";
import { FiFilm, FiArrowRight, FiGrid } from "react-icons/fi";
import TaskCatalogSheet from "./TaskCatalogSheet";

type Props = {
  /** Inject a prompt template into the input (used by quick actions & cards). */
  onUsePrompt: (text: string) => void;
  /**
   * Композер чата (поле ввода) — теперь первый элемент экрана, чтобы поле
   * ввода было видно без прокрутки (ТЗ клиента: «чат вверх»). Слоган,
   * приветствие И логотип убраны отсюда: и то, и другое дублировало шапку
   * чата (свой мини-лого) и HomeHero, который показывается прямо над чатом
   * на главной — см. app/(home)/page.tsx.
   */
  composerSlot?: ReactNode;
  /**
   * Контент между композером и баннером «Создание мультфильмов» — клиент
   * попросил, чтобы сразу после чата шёл блок «Почему EsAI», а уже потом
   * мультфильмы (см. app/(home)/page.tsx, где сюда передаётся WhyEsAI).
   */
  belowComposerSlot?: ReactNode;
  /**
   * Показывать чипы готовых промптов (QUICK_PROMPTS) под композером.
   * По просьбе клиента (24.07.2026) — ТОЛЬКО на /dashboard/text-chat
   * (экран после «Начать бесплатно» для авторизованного визитора), НЕ на
   * главной странице — там уже достаточно контента (Hero, «Почему EsAI»).
   */
  showQuickPrompts?: boolean;
  /** Открыта экранная клавиатура (мобайл) — прижимаем контент к верху, без провала. */
  keyboardOpen?: boolean;
};

type QuickPrompt = {
  icon: string;
  labelKey: string;
  labelDefault: string;
  promptKey: string;
  promptDefault: string;
};

// Готовые примеры запросов под полем ввода — просьба клиента
// (24.07.2026): пустой стартовый экран не вёл пользователя к первому
// сообщению. Клик подставляет промпт в поле ввода (onUsePrompt), не
// отправляет сразу — пользователь успевает уточнить/дополнить.
const QUICK_PROMPTS: QuickPrompt[] = [
  { icon: "✍️", labelKey: "chat.start.quick.article", labelDefault: "Написать статью", promptKey: "chat.start.quick.article_prompt", promptDefault: "Напиши статью на тему: " },
  { icon: "🎨", labelKey: "chat.start.quick.image", labelDefault: "Создать изображение", promptKey: "chat.start.quick.image_prompt", promptDefault: "Нарисуй изображение: " },
  { icon: "🌍", labelKey: "chat.start.quick.translate", labelDefault: "Перевести текст", promptKey: "chat.start.quick.translate_prompt", promptDefault: "Переведи этот текст на английский: " },
  { icon: "📄", labelKey: "chat.start.quick.summarize", labelDefault: "Кратко пересказать документ", promptKey: "chat.start.quick.summarize_prompt", promptDefault: "Кратко перескажи документ, который я прикреплю" },
  { icon: "💻", labelKey: "chat.start.quick.code", labelDefault: "Написать код", promptKey: "chat.start.quick.code_prompt", promptDefault: "Напиши код на Python, который " },
  { icon: "📊", labelKey: "chat.start.quick.study", labelDefault: "Помочь с учёбой", promptKey: "chat.start.quick.study_prompt", promptDefault: "Помоги мне разобраться с темой: " },
  { icon: "✈️", labelKey: "chat.start.quick.travel", labelDefault: "Спланировать путешествие", promptKey: "chat.start.quick.travel_prompt", promptDefault: "Помоги спланировать путешествие в " },
  { icon: "💡", labelKey: "chat.start.quick.business", labelDefault: "Придумать бизнес-идею", promptKey: "chat.start.quick.business_prompt", promptDefault: "Предложи бизнес-идею для " },
];

/**
 * StartScreen — the first screen of the chat: the chat input, quick-prompt
 * chips and the /studio banner. Shown until the first message is sent.
 * Scrolls internally on small screens so the input stays above the fold.
 *
 * The slogan/greeting text and the big brand logo were removed: that
 * pitch/branding is now carried by HomeHero + the chat's own top bar (both
 * already above this component on the home page) — repeating a second big
 * logo here read as redundant. The old quick-actions pills grid, however,
 * is BACK (see QUICK_PROMPTS above) — the product owner asked for it explicitly
 * (24.07.2026): on /dashboard/text-chat (reached after "Начать бесплатно"
 * for an authenticated visitor — see app/dashboard/[[...slug]]/page.tsx,
 * ChatWorkspace mounted there with no heroSlot/belowComposerSlot) this
 * screen had nothing but the composer, centered in a tall empty box. Gated
 * behind showQuickPrompts — the product owner then asked (same day) to keep them OFF the
 * home page, where Hero/WhyEsAI already carry the pitch.
 */
export default function StartScreen({ onUsePrompt, composerSlot, belowComposerSlot, showQuickPrompts, keyboardOpen }: Props) {
  const { t } = useTranslation("common");
  const [catalogOpen, setCatalogOpen] = useState(false);

  return (
    <div className="flex-1 min-h-0 overflow-y-auto w-full">
      <div
        className={
          "max-w-3xl mx-auto w-full min-h-full flex flex-col px-1 " +
          // Top-aligned always (не center) — иначе на «голом» стартовом
          // экране без heroSlot (dashboard) композер проваливался в
          // середину высокого пустого блока (жалоба клиента: «большой
          // пустой отступ сверху», «поднять поле ввода выше»).
          (keyboardOpen ? "justify-start py-3" : "justify-start py-6 sm:py-8")
        }
      >
        {/* Композер — первый элемент экрана, пользователь начинает печатать без прокрутки */}
        {composerSlot ? <div className="w-full">{composerSlot}</div> : null}

        {/* Готовые примеры запросов — один тап подставляет промпт в поле ввода.
            «Все возможности» открывает полный каталог задач (Bottom Sheet) —
            просьба клиента: многие не знают, что вообще умеет EsAI. */}
        {showQuickPrompts && (
          <div className="w-full mt-3 flex flex-wrap gap-2">
            {QUICK_PROMPTS.map((qp) => (
              <button
                key={qp.labelKey}
                type="button"
                onClick={() => onUsePrompt(t(qp.promptKey, { defaultValue: qp.promptDefault }))}
                className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 hover:border-accent/60 hover:text-accent-strong text-foreground text-xs sm:text-sm font-medium px-3 py-1.5 cursor-pointer transition-colors"
              >
                <span aria-hidden>{qp.icon}</span>
                {t(qp.labelKey, { defaultValue: qp.labelDefault })}
              </button>
            ))}
            <button
              type="button"
              onClick={() => setCatalogOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-full border border-accent/50 bg-accent-soft hover:border-accent text-accent-strong text-xs sm:text-sm font-semibold px-3 py-1.5 cursor-pointer transition-colors"
            >
              <FiGrid className="shrink-0" />
              {t("chat.start.quick.all_tasks", { defaultValue: "Все возможности" })}
            </button>
          </div>
        )}

        {showQuickPrompts && (
          <TaskCatalogSheet
            open={catalogOpen}
            onClose={() => setCatalogOpen(false)}
            onSelectPrompt={onUsePrompt}
          />
        )}

        {belowComposerSlot ? <div className="w-full mt-5">{belowComposerSlot}</div> : null}

        {/* Флагман-баннер: «Создание мультфильмов» → студия /studio. Компактная
            карточка-ссылка (сжато по просьбе клиента — раньше была крупнее). */}
        <Link
          href="/studio"
          className="group mt-4 w-full flex items-center gap-3 rounded-xl border border-accent/40 bg-accent-soft px-3 py-2.5 hover:border-accent transition-colors cursor-pointer"
        >
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-surface text-lg">
            🎬
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-2">
              <span className="text-sm font-bold text-foreground">
                {t("chat.start.studio_title", { defaultValue: "Создание мультфильмов" })}
              </span>
              <span className="shrink-0 rounded-full bg-accent px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-on-accent">
                {t("common.new_badge", { defaultValue: "Новинка" })}
              </span>
            </span>
          </span>
          <FiFilm className="hidden sm:block shrink-0 text-lg text-accent" />
          <FiArrowRight className="shrink-0 text-base text-accent transition-transform group-hover:translate-x-0.5" />
        </Link>
      </div>
    </div>
  );
}
