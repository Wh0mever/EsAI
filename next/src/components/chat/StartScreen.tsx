"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import Link from "next/link";
import { FiFilm, FiArrowRight, FiGrid } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
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
   * По просьбе владельца продукта — ТОЛЬКО на /dashboard/text-chat
   * (экран после «Начать бесплатно» для авторизованного визитора), НЕ на
   * главной странице — там уже достаточно контента (Hero, «Почему EsAI»).
   */
  showQuickPrompts?: boolean;
  /**
   * Прижать содержимое к НИЗУ экрана. Включается там, где чат занимает всю
   * высоту вьюпорта (/dashboard/text-chat, без heroSlot): иначе под баннером
   * «Создание мультфильмов» оставалась большая пустая область до футера
   * (просьба клиента: «сдвинь чат в самый низ, чтобы мультфильмы были прямо
   * над соцсетями»). На главной НЕ включается — там чат идёт сразу после
   * Hero и по высоте равен содержимому.
   */
  bottomAligned?: boolean;
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

// Готовые примеры запросов под полем ввода — просьба владельца продукта:
// пустой стартовый экран не вёл пользователя к первому
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

// Карточка «Видеостудия» рядом с мультфильмами — по тому же правилу, что пункт
// меню (components/main/Nav.tsx): только в сборке, где студия открыта всем.
// Иначе посетитель попадал бы с главной на «скоро откроется».
const VSTUDIO_NAV = process.env.NEXT_PUBLIC_VSTUDIO_NAV === "1";

// Вид карточек-ссылок на студии общий: «Видеостудия» — близнец баннера мультфильмов.
const STUDIO_CARD =
  "group w-full flex items-center gap-3 rounded-xl border border-accent/40 bg-accent-soft px-3 py-2.5 hover:border-accent transition-colors cursor-pointer";
const STUDIO_CARD_ICON = "grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-surface text-lg";
const STUDIO_CARD_BADGE =
  "shrink-0 rounded-full bg-accent px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-on-accent";
const STUDIO_CARD_ARROW = "shrink-0 text-base text-accent transition-transform group-hover:translate-x-0.5";
const STUDIO_CARD_DESC = "mt-0.5 block text-xs leading-snug text-muted";

/** Цена склейки — на вкладку: главную открывают часто, а цену меняют только из админки. */
const MERGE_PRICE_KEY = "esai:merge-price";
const MERGE_PRICE_TTL_MS = 10 * 60 * 1000;

function cachedMergePrice(): number | null {
  try {
    const saved = JSON.parse(sessionStorage.getItem(MERGE_PRICE_KEY) || "null") as { price?: unknown; at?: unknown } | null;
    if (!saved || typeof saved.price !== "number" || typeof saved.at !== "number") return null;
    return Date.now() - saved.at < MERGE_PRICE_TTL_MS ? saved.price : null;
  } catch {
    // Нет sessionStorage (приватный режим) — просто спросим сервер.
    return null;
  }
}

/**
 * Склейка сейчас бесплатная? Цена — runtime-ключ сервера (merge/config/), её
 * правят без выкладки: «бесплатно» на карточке говорим только по ответу сервера,
 * иначе при платной склейке главная обещала бы неправду. null — ещё не знаем.
 */
function useMergeFree(): boolean | null {
  const [price, setPrice] = useState<number | null>(null);
  useEffect(() => {
    let alive = true;
    const cached = cachedMergePrice();
    if (cached != null) {
      // Из кэша — тем же путём, что ответ сервера: setState прямо в эффекте линтер не пускает.
      void Promise.resolve().then(() => {
        if (alive) setPrice(cached);
      });
    } else {
      // Без входа: цене всё равно, кто спрашивает, а с токеном сервер считал бы ещё и баланс.
      void fetchData<{ price_credits?: unknown }>("merge/config/", "GET").then((res) => {
        const value = res.ok ? res.data?.price_credits : undefined;
        if (!alive || typeof value !== "number") return;
        setPrice(value);
        try {
          sessionStorage.setItem(MERGE_PRICE_KEY, JSON.stringify({ price: value, at: Date.now() }));
        } catch {
          // Не сохранилось — в следующий раз спросим снова.
        }
      });
    }
    return () => {
      alive = false;
    };
  }, []);
  return price == null ? null : price === 0;
}

/**
 * StartScreen — the first screen of the chat: the chat input, quick-prompt
 * chips and the /studio banner. Shown until the first message is sent.
 * Scrolls internally on small screens so the input stays above the fold.
 *
 * The slogan/greeting text and the big brand logo were removed: that
 * pitch/branding is now carried by HomeHero + the chat's own top bar (both
 * already above this component on the home page) — repeating a second big
 * logo here read as redundant. The old quick-actions pills grid, however,
 * is BACK (see QUICK_PROMPTS above) — the product owner asked for it
 * explicitly: on /dashboard/text-chat (reached after "Начать бесплатно"
 * for an authenticated visitor — see app/dashboard/[[...slug]]/page.tsx,
 * ChatWorkspace mounted there with no heroSlot/belowComposerSlot) this
 * screen had nothing but the composer, centered in a tall empty box. Gated
 * behind showQuickPrompts — the product owner then asked to keep them OFF the
 * home page, where Hero/WhyEsAI already carry the pitch.
 */
export default function StartScreen({ onUsePrompt, composerSlot, belowComposerSlot, showQuickPrompts, bottomAligned, keyboardOpen }: Props) {
  const { t } = useTranslation("common");
  const [catalogOpen, setCatalogOpen] = useState(false);
  const mergeFree = useMergeFree();

  // Прижимаем к низу распоркой, а НЕ justify-end: в прокручиваемом контейнере
  // justify-end обрезает верх, когда содержимое выше экрана, и до него нельзя
  // доскроллить. Распорка на flex-1 схлопывается в 0, если места не осталось,
  // поэтому на маленьких экранах всё остаётся доступным.
  const pushDown = Boolean(bottomAligned) && !keyboardOpen;

  return (
    <div className="flex-1 min-h-0 overflow-y-auto w-full">
      <div
        className={
          "max-w-3xl mx-auto w-full min-h-full flex flex-col px-1 " +
          // Всегда justify-start: вертикальное положение задаёт распорка выше
          // (центрирование когда-то роняло композер в середину пустого блока —
          // жалоба клиента «большой пустой отступ сверху»).
          (keyboardOpen ? "justify-start py-3" : "justify-start py-6 sm:py-8")
        }
      >
        {pushDown ? <div className="flex-1 min-h-0" aria-hidden /> : null}

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
            карточка-ссылка (сжато по просьбе клиента — раньше была крупнее).
            Рядом «Склейка видео», а с флагом сборки — ещё «Видеостудия». На
            телефоне карточки идут друг под другом; три встают в ряд с 768 px
            (уже заголовки с «Новинкой» не помещались), две — с 640 px. Высоты
            ровные: ячейки сетки тянутся по самой высокой. */}
        <div className={VSTUDIO_NAV ? "mt-4 grid w-full gap-2 md:grid-cols-3" : "mt-4 grid w-full gap-2 sm:grid-cols-2"}>
          <Link href="/studio" className={STUDIO_CARD}>
            <span className={STUDIO_CARD_ICON}>
              🎬
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-sm font-bold text-foreground">
                  {t("chat.start.studio_title", { defaultValue: "Создание мультфильмов" })}
                </span>
                <span className={STUDIO_CARD_BADGE}>
                  {t("common.new_badge", { defaultValue: "Новинка" })}
                </span>
              </span>
              {/* Описание есть у всех трёх карточек: без него ряд выглядел неровным. */}
              <span className={STUDIO_CARD_DESC}>
                {t("chat.start.studio_desc", {
                  defaultValue: "Выберите героя и сцены — мультфильм с озвучкой за несколько минут",
                })}
              </span>
            </span>
            {/* В ряду карточка уже: декоративный значок съедал место заголовка, и
                «Новинка» упиралась в стрелку. Две карточки — значок с 1024 px. */}
            {VSTUDIO_NAV ? null : <FiFilm className="hidden lg:block shrink-0 text-lg text-accent" />}
            <FiArrowRight className={STUDIO_CARD_ARROW} />
          </Link>

          {VSTUDIO_NAV ? (
            <Link href="/video-studio" className={STUDIO_CARD}>
              <span className={STUDIO_CARD_ICON} aria-hidden>
                🎥
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-sm font-bold text-foreground">
                    {t("chat.start.vstudio_title", { defaultValue: "Видеостудия" })}
                  </span>
                  <span className={STUDIO_CARD_BADGE}>
                    {t("common.new_badge", { defaultValue: "Новинка" })}
                  </span>
                </span>
                {/* Одна строка о том, чем студия отличается от мультфильмов по
                    соседству: свой запрос и свои фото вместо готовых сцен. */}
                <span className={STUDIO_CARD_DESC}>
                  {t("chat.start.vstudio_desc", {
                    defaultValue: "Видео и картинки по описанию и вашим фото — несколько моделей в одном окне",
                  })}
                </span>
              </span>
              <FiArrowRight className={STUDIO_CARD_ARROW} />
            </Link>
          ) : null}

          {/* Склейка открыта всем (своего флага у неё нет), как и мультстудия. */}
          <Link href="/merge" prefetch={false} className={STUDIO_CARD}>
            <span className={STUDIO_CARD_ICON} aria-hidden>
              🎞️
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-sm font-bold text-foreground">
                  {t("chat.start.merge_title", { defaultValue: "Склейка видео" })}
                </span>
                <span className={STUDIO_CARD_BADGE}>
                  {t("common.new_badge", { defaultValue: "Новинка" })}
                </span>
              </span>
              <span className={STUDIO_CARD_DESC}>
                {mergeFree
                  ? t("chat.start.merge_desc_free", {
                      defaultValue: "Соедините ролики из студий, чата и свои видео в один ролик — бесплатно",
                    })
                  : t("chat.start.merge_desc", {
                      defaultValue: "Соедините ролики из студий, чата и свои видео в один ролик",
                    })}
              </span>
            </span>
            <FiArrowRight className={STUDIO_CARD_ARROW} />
          </Link>
        </div>
      </div>
    </div>
  );
}
