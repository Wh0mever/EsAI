"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiCheck } from "react-icons/fi";
import { useCurrency } from "@/hooks/useCurrency";
import { convertFromKgs } from "@/lib/currency";
import { fetchData } from "@/tools/fetchData";

/**
 * PAY-AS-YOU-GO banner — клиентский референс (скрин с другого сайта),
 * адаптированный под тёмную палитру EsAI. Используется в местах, где виден
 * баланс/пополнение (клиент явно попросил именно это — «где пополнять
 * баланс... добавь ещё тоже»):
 *  - /pricing, ДО карточек пакетов (TokenPackages) — так просил клиент;
 *    здесь это единственный <h1> страницы (старую плашку
 *    packages.subtitle/title/lead убрали из page.tsx как дублирующую).
 *  - главная страница, над превью тарифов (HomePricingPreview) — клиент
 *    попросил закрыть жалобу «не везде рубли есть» (валюту без /pricing
 *    было не переключить). На главной уже есть свой <h1> в HomeHero,
 *    поэтому здесь заголовок рендерится как <h2> (headingLevel="h2").
 *  - TopUpModal (клик по балансу ⚡ в шапке чата) и UserBalanceCard
 *    (баланс в /profile) — compact=true, тем же текстом, но «мелким
 *    шрифтом» (дословная просьба клиента), без бейджа-эйброу и без
 *    заголовка h1/h2 (там уже есть свой заголовок карточки/модалки).
 */
type Props = {
  headingLevel?: "h1" | "h2";
  /** Мелкий текстовый вариант для тесных мест (TopUpModal, UserBalanceCard) — без бейджа и без h1/h2. */
  compact?: boolean;
  /**
   * format() родителя, у которого стоит CurrencySwitch. Свой useCurrency() баннера
   * с ним не синхронизирован: после переключения валюты чип «Старт от» оставался
   * в старой валюте, пока карточки уже показывали новую.
   */
  format?: (priceKgs: number, somLabel?: string) => string;
};

/**
 * Самый дешёвый активный пакет, в сомах. Один запрос на вкладку: баннер стоит
 * сразу в нескольких местах. Раньше «от 190» было вписано в текст и осталось на
 * витрине, когда пакет за 190 сом сняли с продажи.
 */
let cheapestPromise: Promise<number | null> | null = null;
function fetchCheapest(): Promise<number | null> {
  if (!cheapestPromise) {
    cheapestPromise = fetchData<{ price: number }[]>("plans/packages/", "GET", null, false)
      .then((res) => {
        const prices = (Array.isArray(res.data) ? res.data : [])
          .map((p) => Number(p.price))
          .filter((n) => Number.isFinite(n) && n > 0);
        if (!prices.length) throw new Error("no packages");
        return Math.min(...prices);
      })
      .catch(() => {
        cheapestPromise = null; // следующий баннер попробует снова
        return null;
      });
  }
  return cheapestPromise;
}

export default function PayAsYouGoBanner({ headingLevel = "h1", compact = false, format: parentFormat }: Props) {
  const { t, i18n } = useTranslation("common");
  const { cryptoEnabled, format: ownFormat, usdRate } = useCurrency();
  const format = parentFormat ?? ownFormat;
  const Heading = headingLevel;
  const [cheapest, setCheapest] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    void fetchCheapest().then((price) => {
      if (alive) setCheapest(price);
    });
    return () => {
      alive = false;
    };
  }, []);

  const usdt =
    cheapest !== null
      ? convertFromKgs(cheapest, "USD", 0, usdRate).toLocaleString(
          i18n.language === "en" ? "en-US" : "ru-RU",
          { maximumFractionDigits: 1 },
        )
      : "";

  const checks = [
    t("packages.payg_check_no_subscription", { defaultValue: "Без подписок" }),
    t("packages.payg_check_no_hidden_fees", { defaultValue: "Без скрытых платежей" }),
    // Пока цена не пришла — плашку не показываем, чем показывать неправду.
    ...(cheapest !== null
      ? [t("packages.payg_check_starts_from", {
          price: format(cheapest, t("topup.som", { defaultValue: "сом" })),
          defaultValue: "Старт от {{price}}",
        })]
      : []),
    // Плашка про крипту живёт вместе с самим способом оплаты: выключили
    // крипту в админке — обещание с витрины исчезло само.
    ...(cryptoEnabled && usdt
      ? [t("packages.payg_check_crypto", { amount: usdt, defaultValue: "От ≈ {{amount}} USDT в криптовалюте" })]
      : []),
  ];

  if (compact) {
    // Без text-center/items-center — наследует выравнивание родителя
    // (лево в UserBalanceCard, центр — заворачивается снаружи в TopUpModal).
    return (
      <div className="flex flex-col gap-1">
        <p className="text-xs font-semibold text-foreground">
          {t("packages.payg_title", {
            defaultValue: "Никаких подписок. Платите только за то, что используете.",
          })}
        </p>
        <p className="text-[11px] text-muted leading-snug">
          {t("packages.payg_subtitle", {
            defaultValue:
              "Пополняете баланс — и тратите его только на реальное использование нейросетей. Не пользуетесь — ничего не списываем.",
          })}
        </p>
        <p className="text-[11px] text-muted">{checks.join(" · ")}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-2 text-center px-4 pb-2">
      <span className="px-3 py-1 rounded-full bg-accent/15 border border-accent/30 text-[11px] font-bold tracking-wider text-accent-strong uppercase">
        {t("packages.payg_badge", { defaultValue: "PAY-AS-YOU-GO" })}
      </span>

      <Heading className="text-2xl sm:text-3xl font-bold max-w-2xl">
        {t("packages.payg_title", {
          defaultValue: "Никаких подписок. Платите только за то, что используете.",
        })}
      </Heading>

      <p className="text-muted text-sm sm:text-base max-w-xl">
        {t("packages.payg_subtitle", {
          defaultValue:
            "Пополняете баланс — и тратите его только на реальное использование нейросетей. Не пользуетесь — ничего не списываем.",
        })}
      </p>

      <div className="flex flex-wrap items-center justify-center gap-2 mt-1">
        {checks.map((label) => (
          <span
            key={label}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-surface-2 border border-border text-xs sm:text-sm font-medium text-foreground"
          >
            <FiCheck className="text-accent-strong shrink-0" size={14} />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}
