"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronLeft, FiChevronRight, FiGift, FiZap } from "react-icons/fi";
import type { PackageNeed } from "@/lib/packagePick";

/**
 * Выбор пакета кредитов — один и тот же в мультстудии и видеостудии.
 *
 * Клиент разобрал воронку: из тысячи человек, открывших тарифы, «Пополнить»
 * нажали двести. Терялись они до оплаты — на длинных объяснениях и
 * вертикальном списке, который надо было листать вниз. Поэтому здесь сразу
 * короткая шапка и карусель: свайп или стрелки, «2 / 5», соседняя карточка
 * выглядывает с края — видно, что пакетов больше.
 *
 * Компонент только рисует. Пакеты, оплата и подписи «на что хватит» приходят
 * от хозяина (TokenPackages на странице тарифов студии, TopUpModal в
 * видеостудии): платёжные пути у них свои и проверены, их не трогаем.
 */

export type CarouselPkg = {
  id: number | string;
  name: string;
  tokens: number;
  bonus_tokens?: number;
  price: number;
  badge?: string;
  featured?: boolean;
};

export type CarouselValue = { title: string; rows: string[] } | null;

type Props<P extends CarouselPkg> = {
  packages: P[];
  /** Какой пакет показать первым (подходящий под нехватку). null — первый по порядку. */
  startId?: number | string | null;
  /** Подпись на подходящем пакете: «Хватит на текущую съёмку». */
  recommendLabel?: string;
  /** Цена в выбранной валюте (со скидкой, если она есть). */
  price: (p: P) => ReactNode;
  /** «Примерно хватит на» — у каждой студии своё. */
  value: (p: P) => CarouselValue;
  buyLabel: (p: P) => string;
  onBuy: (p: P) => void;
  /** Идёт покупка: кнопки заблокированы. */
  busy?: boolean;
};

export default function PackageCarousel<P extends CarouselPkg>({
  packages,
  startId = null,
  recommendLabel,
  price,
  value,
  buyLabel,
  onBuy,
  busy = false,
}: Props<P>) {
  const { t } = useTranslation("common");
  const scroller = useRef<HTMLDivElement>(null);
  const [index, setIndex] = useState(0);
  const count = packages.length;
  const startIndex = Math.max(0, packages.findIndex((p) => String(p.id) === String(startId)));
  const highlightId =
    startId != null && packages.some((p) => String(p.id) === String(startId))
      ? String(startId)
      : String(packages.find((p) => p.featured)?.id ?? "");

  /** Левый край прокрутки, при котором карточка i стоит по центру.
   *  offsetLeft считается от ленты: у неё position: relative. */
  const leftFor = useCallback((i: number) => {
    const box = scroller.current;
    const card = box?.children[i] as HTMLElement | undefined;
    if (!box || !card) return 0;
    return card.offsetLeft - (box.clientWidth - card.clientWidth) / 2;
  }, []);

  const go = useCallback(
    (i: number, smooth = true) => {
      const box = scroller.current;
      if (!box || count === 0) return;
      const next = Math.min(count - 1, Math.max(0, i));
      setIndex(next);
      box.scrollTo({ left: leftFor(next), behavior: smooth ? "smooth" : "auto" });
    },
    [count, leftFor]
  );

  // Пакеты пришли (или сменилась нехватка) — сразу встаём на нужный, без анимации.
  useEffect(() => {
    if (count === 0) return;
    const id = requestAnimationFrame(() => go(startIndex, false));
    return () => cancelAnimationFrame(id);
  }, [count, startIndex, go]);

  // Свайп: текущей считаем карточку, чей центр ближе к центру ленты.
  const onScroll = () => {
    const box = scroller.current;
    if (!box) return;
    const middle = box.scrollLeft + box.clientWidth / 2;
    let best = 0;
    let bestGap = Infinity;
    Array.from(box.children).forEach((el, i) => {
      const c = el as HTMLElement;
      const gap = Math.abs(c.offsetLeft + c.clientWidth / 2 - middle);
      if (gap < bestGap) {
        bestGap = gap;
        best = i;
      }
    });
    if (best !== index) setIndex(best);
  };

  if (count === 0) return null;

  return (
    <div className="w-full">
      <div
        ref={scroller}
        onScroll={onScroll}
        tabIndex={0}
        aria-roledescription={t("pkg_picker.carousel", { defaultValue: "карусель" })}
        className="relative flex snap-x snap-mandatory items-stretch gap-3 overflow-x-auto overscroll-x-contain px-[7%] pb-1 pt-1 outline-none [scrollbar-width:none] sm:px-[calc(50%-170px)] [&::-webkit-scrollbar]:hidden"
      >
        {packages.map((p, i) => {
          const v = value(p);
          const lit = String(p.id) === highlightId;
          const recommended = recommendLabel && startId != null && String(p.id) === String(startId);
          return (
            <div
              key={p.id}
              aria-label={`${i + 1} / ${count}`}
              className={`flex w-[86%] shrink-0 snap-center flex-col gap-3 rounded-2xl bg-surface p-4 transition-colors sm:w-[340px] sm:p-5 ${
                lit ? "border-2 border-accent shadow-lg shadow-accent/10" : "border border-border"
              }`}
            >
              <div className="flex min-h-[1.75rem] flex-wrap items-center justify-between gap-2">
                <span className="text-lg font-bold uppercase tracking-wide text-foreground">{p.name}</span>
                {recommended ? (
                  <span className="rounded-full border border-accent/50 bg-accent/15 px-2.5 py-1 text-[10px] font-bold uppercase leading-tight tracking-wide text-accent-strong sm:text-[11px]">
                    {recommendLabel}
                  </span>
                ) : p.badge && p.badge.trim() ? (
                  <span className="rounded-full bg-accent/15 px-2.5 py-1 text-[11px] font-semibold text-accent-strong">
                    {p.badge}
                  </span>
                ) : null}
              </div>

              <div>
                <div className="whitespace-nowrap text-[1.75rem] font-extrabold leading-tight text-foreground sm:text-4xl">
                  {t("pkg_picker.credits", {
                    defaultValue: "{{amount}} кредитов",
                    count: Number(p.tokens) || 0,
                    amount: (Number(p.tokens) || 0).toLocaleString("ru-RU"),
                  })}
                </div>
                {!!p.bonus_tokens && p.bonus_tokens > 0 && (
                  <div className="mt-1 inline-flex items-center gap-1 text-sm text-accent">
                    <FiGift /> +{p.bonus_tokens.toLocaleString("ru-RU")} {t("topup.bonus", { defaultValue: "бонус" })}
                  </div>
                )}
                <div className="mt-1 text-xl font-bold text-foreground">{price(p)}</div>
              </div>

              <div className="flex min-h-[7.5rem] flex-col gap-1.5 rounded-xl border border-border bg-surface-2 px-3.5 py-3">
                {v && v.rows.length > 0 && (
                  <>
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">{v.title}</div>
                    <ul className="flex flex-col gap-1 text-sm text-foreground">
                      {v.rows.map((r) => (
                        <li key={r} className="flex gap-2">
                          <span aria-hidden className="mt-[0.45rem] h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                          {/* Эмодзи в начале строк остались от старых витрин — здесь вместо них точка. */}
                          <span>{r.replace(/^[^\p{L}\p{N}]+/u, "")}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </div>

              <button
                type="button"
                onClick={() => onBuy(p)}
                disabled={busy}
                className="mt-auto inline-flex items-center justify-center gap-2 rounded-xl bg-accent py-3 text-sm font-bold uppercase tracking-wide text-on-accent transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60 cursor-pointer"
              >
                <FiZap />
                {buyLabel(p)}
              </button>
            </div>
          );
        })}
      </div>

      {count > 1 && (
        <div className="mt-3 flex items-center justify-between gap-3 px-1">
          <button
            type="button"
            onClick={() => go(index - 1)}
            disabled={index === 0}
            aria-label={t("pkg_picker.prev", { defaultValue: "Предыдущий пакет" })}
            className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-border bg-surface text-xl text-foreground transition-colors hover:border-accent disabled:opacity-30 cursor-pointer disabled:cursor-default"
          >
            <FiChevronLeft />
          </button>
          <div className="flex min-w-0 flex-col items-center gap-1">
            <div className="flex items-center gap-1.5">
              {packages.map((p, i) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => go(i)}
                  aria-label={`${i + 1} / ${count}`}
                  aria-current={i === index}
                  className={`h-2 rounded-full transition-all cursor-pointer ${
                    i === index ? "w-5 bg-accent" : "w-2 bg-muted/40 hover:bg-muted"
                  }`}
                />
              ))}
            </div>
            <div className="text-xs text-muted">
              <span className="font-semibold text-foreground">
                {index + 1} / {count}
              </span>{" "}
              · {t("pkg_picker.swipe", { defaultValue: "листайте влево и вправо" })}
            </div>
          </div>
          <button
            type="button"
            onClick={() => go(index + 1)}
            disabled={index === count - 1}
            aria-label={t("pkg_picker.next", { defaultValue: "Следующий пакет" })}
            className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-border bg-surface text-xl text-foreground transition-colors hover:border-accent disabled:opacity-30 cursor-pointer disabled:cursor-default"
          >
            <FiChevronRight />
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * Шапка выбора пакета: заголовок, одна строка пояснения, нехватка (если
 * пришли с операции) и переключатель валют — общая для обеих студий.
 */
export function PackagePickerHead({
  need,
  switcher,
  as: Tag = "h2",
  showTitle = true,
}: {
  need?: PackageNeed | null;
  /** CurrencySwitch хозяина: валюта общая с остальным сайтом. */
  switcher: ReactNode;
  as?: "h1" | "h2";
  /** В модалке заголовок уже в рамке окна. */
  showTitle?: boolean;
}) {
  const { t } = useTranslation("common");
  return (
    <div className="flex w-full flex-col gap-3">
      {showTitle && (
        <Tag className="text-2xl font-bold text-foreground sm:text-3xl">
          {t("pkg_picker.title", { defaultValue: "Выберите пакет кредитов" })}
        </Tag>
      )}
      {need && need.missing > 0 && (
        <div className="rounded-xl border border-accent/50 bg-accent/10 px-4 py-2.5 text-sm font-semibold text-accent-strong">
          {t(need.for === "scene" ? "pkg_picker.short_scene" : "pkg_picker.short_generation", {
            count: need.missing,
            defaultValue:
              need.for === "scene"
                ? "Не хватает {{count}} кредитов для съёмки"
                : "Не хватает {{count}} кредитов для генерации",
          })}
        </div>
      )}
      <p className="text-sm text-muted">
        {t("pkg_picker.note", {
          defaultValue: "Без подписки. Кредиты не сгорают и доступны во всех инструментах EsAI.",
        })}
      </p>
      <div className="flex justify-start">{switcher}</div>
    </div>
  );
}

/** Подпись на подходящем пакете — съёмка у мультстудии, генерация у остальных. */
export function recommendLabelKey(need: PackageNeed | null | undefined): string | null {
  if (!need || need.missing <= 0) return null;
  return need.for === "scene" ? "pkg_picker.fits_scene" : "pkg_picker.fits_generation";
}
