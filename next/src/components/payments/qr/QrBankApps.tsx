"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronDown, FiExternalLink } from "react-icons/fi";
import { appNotOpened, appsForPlatform, isHttpsUrl, isSafeAppUrl, splitApps } from "@/lib/qrpay";
import type { QrPlatform } from "@/lib/qrpay";
import { trackFunnel } from "@/tools/funnel";
import type { QrApp } from "@/types/qrpay";

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

function BankIcon({ app }: { app: QrApp }) {
  const [broken, setBroken] = useState(false);
  const letter = (app.name || app.code || "?").trim().charAt(0).toUpperCase();
  if (!broken && isHttpsUrl(app.icon)) {
    return (
      // Значок банка лежит на чужом сервере и нужен на секунду: оптимизатор
      // картинок Next тут ни к чему.
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={app.icon}
        alt=""
        width={36}
        height={36}
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => setBroken(true)}
        className="h-9 w-9 shrink-0 rounded-xl bg-white object-contain"
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-surface-3 text-base font-bold text-foreground"
    >
      {letter}
    </span>
  );
}

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

  const { main, rest } = splitApps(appsForPlatform(apps, platform));
  const shown = showAll ? [...main, ...rest] : main;
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

  return (
    <section className="flex flex-col gap-2.5">
      <div className="text-sm font-semibold text-foreground">
        {t("apps_title", { defaultValue: "Открыть в приложении банка" })}
      </div>

      {shown.length > 0 ? (
        <div className="grid grid-cols-2 gap-2">
          {shown.map((app) =>
            isSafeAppUrl(app.url) ? (
              <a
                key={`${app.code}:${app.url}`}
                href={app.url}
                onClick={() => onAppClick(app)}
                className="flex min-h-[52px] items-center gap-2.5 rounded-xl border border-border bg-surface-2 px-3 py-2 text-left transition-colors hover:border-accent/70 hover:bg-surface-3 active:bg-surface-3"
              >
                <BankIcon app={app} />
                <span className="min-w-0 flex-1 break-words text-sm font-medium leading-tight text-foreground">
                  {app.name || app.code}
                </span>
              </a>
            ) : null
          )}
        </div>
      ) : (
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
          className="inline-flex cursor-pointer items-center justify-center gap-1.5 rounded-xl border border-dashed border-border px-3 py-2.5 text-sm text-muted transition-colors hover:border-accent/60 hover:text-foreground"
        >
          <FiChevronDown />
          {t("show_all_banks", { defaultValue: "Показать все банки" })}
          <span className="tabular-nums text-muted-2">+{rest.length}</span>
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
          className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-xl border border-border bg-surface px-3 py-2.5 text-sm font-medium text-foreground transition-colors hover:border-accent/70"
        >
          <FiExternalLink className="shrink-0" />
          {t("all_banks", { defaultValue: "Все банки / другой банк" })}
        </a>
      )}
    </section>
  );
}
