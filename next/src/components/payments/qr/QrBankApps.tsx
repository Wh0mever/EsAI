"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiArrowRight, FiChevronDown, FiExternalLink } from "react-icons/fi";
import { appNotOpened, appsForPlatform, isHttpsUrl, isSafeAppUrl, splitApps, splitFeatured } from "@/lib/qrpay";
import type { QrPlatform } from "@/lib/qrpay";
import { trackFunnel } from "@/tools/funnel";
import type { QrApp } from "@/types/qrpay";
import BankIcon from "./BankIcon";

/**
 * Кнопки «открыть в приложении банка» — для телефона, где свой же экран не
 * отсканируешь.
 *
 * Каждая кнопка — НАСТОЯЩАЯ ссылка <a href>, а не window.location из
 * обработчика: только на живое нажатие по ссылке срабатывают универсальные
 * ссылки iOS и правила встроенных браузеров. Мы лишь считаем нажатие и через
 * пару секунд, если страница так и не уходила с экрана, подсказываем запасной
 * путь.
 *
 * Банк узнают по значку приложения, а не по подписи — поэтому значки крупные.
 * МБанк стоит отдельной широкой кнопкой сверху: он есть почти у каждого, и
 * большинству не нужно искать свой банк в сетке.
 *
 * Кнопка «Все банки / другой банк» ведёт на страницу оплаты GoPay и не зависит
 * от списка приложений: когда список пуст или ссылок нет, она и есть выход.
 */
type Props = {
  apps: QrApp[];
  platform: QrPlatform;
  checkoutUrl: string;
  packageId: number | string | null;
};

/** Сколько ждём, прежде чем решить, что приложение банка не открылось. */
const NOT_OPENED_AFTER_MS = 2500;

// Часы читаются только в обработчиках (нажатие на банк и его таймер), не при
// рендере. Отдельная функция — чтобы правило чистоты рендера не принимало
// обработчик, собранный внутри .map(), за код рендера.
const nowMs = (): number => Date.now();

export default function QrBankApps({ apps, platform, checkoutUrl, packageId }: Props) {
  const { t } = useTranslation("qrpay", { useSuspense: false });
  const [showAll, setShowAll] = useState(false);
  const [notOpened, setNotOpened] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Уходила ли страница с экрана после нажатия на банк. Одного взгляда на
  // document.hidden в момент срабатывания таймера мало: iOS замораживает
  // таймеры ушедшей вкладки, и он срабатывает, когда человек уже вернулся из
  // банка — страница снова видна, хотя приложение открылось.
  const wentHidden = useRef(false);

  useEffect(() => {
    // Страница ушла с экрана — если это после нажатия на банк, приложение
    // открылось. Запоминаем; решает таймер нажатия (appNotOpened).
    const markAway = () => {
      wentHidden.current = true;
    };
    // visibilitychange приходит в обе стороны — нужен только уход.
    const onVisibility = () => {
      if (document.hidden) markAway();
    };
    document.addEventListener("visibilitychange", onVisibility);
    // pagehide бывает и без смены видимости (страницу выгружают).
    window.addEventListener("pagehide", markAway);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", markAway);
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  // Набор банков тот же, что и раньше, — меняется только раскладка: главный
  // банк вынут из сетки наверх.
  const { featured: top, others } = splitFeatured(appsForPlatform(apps, platform));
  // Та же проверка ссылки, что и у кнопок сетки ниже.
  const featured = top && isSafeAppUrl(top.url) ? top : null;
  const { main, rest } = splitApps(others);
  const shown = showAll ? [...main, ...rest] : main;
  const hasApps = Boolean(featured) || shown.length > 0;
  const checkout = isHttpsUrl(checkoutUrl) ? checkoutUrl : "";

  const onAppClick = (app: QrApp) => {
    // Ничего не отменяем: переход делает сама ссылка.
    trackFunnel("kgs_qr_app_open", { package_id: packageId, app: app.code });
    setNotOpened(false);
    if (timer.current) clearTimeout(timer.current);
    wentHidden.current = false;
    const startedAt = nowMs();
    timer.current = setTimeout(() => {
      timer.current = null;
      // Страница так и не уходила с экрана — значит, приложение банка не
      // открылось (не установлено, или браузер не пустил ссылку).
      if (appNotOpened(wentHidden.current, document.hidden, nowMs() - startedAt, NOT_OPENED_AFTER_MS)) {
        setNotOpened(true);
      }
    }, NOT_OPENED_AFTER_MS);
  };

  const steps = [
    t("m_step_1", { defaultValue: "Выберите банк" }),
    t("m_step_2", { defaultValue: "Подтвердите оплату в приложении" }),
    t("m_step_3", { defaultValue: "Вернитесь — кредиты уже на балансе" }),
  ];

  return (
    <section className="flex flex-col gap-3">
      <div className="text-[15px] font-semibold leading-tight text-foreground">
        {t("apps_title", { defaultValue: "Открыть в приложении банка" })}
      </div>

      {/* Три шага — только когда есть что нажимать: без кнопок банков
          «выберите банк» сбивало бы с толку. */}
      {hasApps && (
        <ol className="flex flex-col gap-2">
          {steps.map((text, i) => (
            <li
              key={i}
              className="relative flex items-start gap-2.5 text-[13px] leading-5 text-muted before:absolute before:-bottom-2 before:left-[9.5px] before:top-5 before:w-px before:bg-border-strong last:before:hidden"
            >
              <span
                aria-hidden="true"
                className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent/15 text-[11px] font-bold tabular-nums text-accent"
              >
                {i + 1}
              </span>
              <span className="min-w-0 flex-1">{text}</span>
            </li>
          ))}
        </ol>
      )}

      {featured && (
        <a
          href={featured.url}
          onClick={() => onAppClick(featured)}
          className="group relative mt-1.5 flex min-h-[76px] items-center gap-3.5 rounded-2xl border border-accent/60 bg-accent/[0.07] px-3.5 py-3 text-left transition-colors hover:border-accent hover:bg-accent/[0.12] active:bg-accent/[0.16]"
        >
          <span className="absolute -top-2.5 right-3 rounded-full bg-accent px-2 py-0.5 text-[10px] font-semibold leading-4 text-on-accent">
            {t("featured_badge", { defaultValue: "Самый популярный" })}
          </span>
          <BankIcon code={featured.code} name={featured.name} icon={featured.icon} size={48} />
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="break-words text-base font-semibold leading-tight text-foreground">
              {featured.name || featured.code}
            </span>
            <span className="text-xs leading-snug text-muted">
              {t("featured_caption", { defaultValue: "Сумма уже указана — останется подтвердить" })}
            </span>
          </span>
          <span
            aria-hidden="true"
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-on-accent transition-transform group-hover:translate-x-0.5"
          >
            <FiArrowRight className="h-[18px] w-[18px]" />
          </span>
        </a>
      )}

      {shown.length > 0 && (
        <div className="grid grid-cols-2 gap-2">
          {shown.map((app) =>
            isSafeAppUrl(app.url) ? (
              <a
                key={`${app.code}:${app.url}`}
                href={app.url}
                onClick={() => onAppClick(app)}
                className="flex min-h-[60px] items-center gap-2.5 rounded-2xl border border-border bg-surface-2 px-2.5 py-2.5 text-left transition-colors hover:border-accent/70 hover:bg-surface-3 active:bg-surface-3"
              >
                <BankIcon code={app.code} name={app.name} icon={app.icon} size={40} />
                <span className="min-w-0 flex-1 break-words text-sm font-medium leading-tight text-foreground">
                  {app.name || app.code}
                </span>
              </a>
            ) : null
          )}
        </div>
      )}

      {!hasApps && (
        <p className="rounded-xl border border-border bg-surface-2 px-3 py-2.5 text-sm leading-snug text-muted">
          {t("no_apps_hint", {
            defaultValue:
              "Сохраните QR-код и откройте его в приложении банка: «Оплата по QR» → «Из галереи». Или откройте страницу со всеми банками.",
          })}
        </p>
      )}

      {rest.length > 0 && !showAll && (
        <button
          type="button"
          onClick={() => setShowAll(true)}
          aria-expanded={false}
          className="inline-flex min-h-[52px] cursor-pointer items-center justify-center gap-2 rounded-2xl border border-dashed border-border-strong px-3 py-2 text-sm text-muted transition-colors hover:border-accent/60 hover:text-foreground"
        >
          {/* Значки спрятанных банков: видно, есть ли среди них свой, ещё до нажатия. */}
          <span aria-hidden="true" className="flex shrink-0 items-center gap-1">
            {rest.slice(0, 3).map((app) => (
              <BankIcon key={app.code} code={app.code} name={app.name} icon={app.icon} size={22} />
            ))}
          </span>
          <span className="min-w-0">{t("show_all_banks", { defaultValue: "Показать все банки" })}</span>
          <span className="tabular-nums text-muted-2">+{rest.length}</span>
          <FiChevronDown className="shrink-0" />
        </button>
      )}

      {notOpened && (
        <p
          role="status"
          className="rounded-xl border border-status-wait/30 bg-status-wait/10 px-3 py-2 text-xs leading-snug text-foreground"
        >
          {t("app_not_opened", {
            defaultValue:
              "Приложение не открылось? Сохраните QR-код и оплатите через сканер в банке или выберите другой банк.",
          })}
        </p>
      )}

      {checkout && (
        <a
          href={checkout}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-h-[52px] items-center justify-center gap-2 rounded-2xl border border-border bg-surface px-3 py-2.5 text-sm font-medium text-foreground transition-colors hover:border-accent/70"
        >
          <FiExternalLink className="shrink-0" />
          {t("all_banks", { defaultValue: "Все банки / другой банк" })}
        </a>
      )}
    </section>
  );
}
