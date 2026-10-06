"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  FiAlertTriangle,
  FiCheckCircle,
  FiDownload,
  FiExternalLink,
  FiLoader,
  FiRefreshCw,
} from "react-icons/fi";
import CopyField from "@/components/ui/CopyField";
import QrCode from "@/components/ui/QrCode";
import { formatCountdown } from "@/lib/cryptoUri";
import { formatPrice } from "@/lib/currency";
import { detectEmbed, detectPlatform, isHttpsUrl, isQrInvoice, otherMethodStep, qrFileName } from "@/lib/qrpay";
import type { QrCancelPhase, QrEmbed, QrPlatform } from "@/lib/qrpay";
import { clearQrSession, saveQrSession } from "@/lib/qrSession";
import { useQrInvoice } from "@/hooks/useQrInvoice";
import { fetchData } from "@/tools/fetchData";
import { trackFunnel } from "@/tools/funnel";
import type { QrCancelResult, QrInvoice, QrUiState } from "@/types/qrpay";
import QrBankApps from "./QrBankApps";
import QrStatusPill from "./QrStatusPill";
import { renderQrPng, saveQrImage } from "./saveQrImage";

/**
 * Экран оплаты по единому QR: код, сумма, таймер и живой статус.
 *
 * Одна вёрстка, две раскладки. На компьютере код сканируют телефоном —
 * слева QR, справа три шага. На телефоне свой экран не отсканируешь, поэтому
 * сверху кнопки банков, а QR ниже — его можно сохранить и загрузить в банке
 * «из галереи». QR и опрос остаются на нашем экране в любом случае: когда
 * человек вернётся из банка, он увидит «Оплачено».
 *
 * Кнопки «Я оплатил» нет намеренно (как и у крипты): она ничего не решает,
 * зато создаёт чувство, будто без неё деньги не зачтут. Закрытие окна оплату
 * не отменяет — об этом сказано прямым текстом.
 */
type Pkg = {
  id: number | string;
  name: string;
  tokens: number;
  bonus_tokens?: number;
};

type Props = {
  orderId: string;
  /** счёт из ответа на создание; нет — возвращаемся к счёту по номеру */
  initial?: QrInvoice | null;
  pkg?: Pkg | null;
  deviceKey?: string;
  returnTo?: string;
  /** «Создать новый QR-код» сохраняет выбор «без скидки» того, кто нас открыл */
  fullPrice?: boolean;
  onPaid?: (invoice: QrInvoice) => void;
  /** вернуться к выбору способа; нет — действие просто закрывает окно */
  onOtherMethod?: () => void;
  onClose: () => void;
};

type QrEnv = { platform: QrPlatform; embed: QrEmbed; mobile: boolean };

const DESKTOP_ENV: QrEnv = { platform: "desktop", embed: "browser", mobile: false };

type TelegramHost = { Telegram?: { WebApp?: { initData?: unknown; openLink?: (url: string) => void } } };

/** Где мы открыты. Догадка по user-agent — на ней ничего критичного не держится. */
function readEnv(): QrEnv {
  if (typeof window === "undefined" || typeof navigator === "undefined") return DESKTOP_ENV;
  try {
    const ua = navigator.userAgent || "";
    const platform = detectPlatform(ua, navigator.platform, navigator.maxTouchPoints);
    let coarse = false;
    try {
      coarse = Boolean(window.matchMedia?.("(pointer: coarse)").matches);
    } catch {
      coarse = false;
    }
    return {
      platform,
      embed: detectEmbed(ua, window as unknown as TelegramHost),
      mobile: platform !== "desktop" || coarse,
    };
  } catch {
    return DESKTOP_ENV;
  }
}

/** Сколько держим человека на QR, когда банк уже обрабатывает оплату по нему. */
const CANCEL_HOLD_MS = 30 * 1000;

const BTN_PRIMARY =
  "inline-flex min-h-[44px] cursor-pointer items-center justify-center gap-2 rounded-xl bg-accent px-5 py-2.5 text-center text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong disabled:cursor-wait disabled:opacity-60";
const BTN_SECONDARY =
  "inline-flex min-h-[44px] cursor-pointer items-center justify-center gap-2 rounded-xl border border-border bg-surface-2 px-4 py-2.5 text-center text-sm font-medium text-foreground transition-colors hover:bg-surface-3 disabled:cursor-default disabled:opacity-60";
const BTN_LINK =
  "inline-flex min-h-[44px] cursor-pointer items-center justify-center gap-1.5 px-2 text-sm text-muted underline-offset-4 transition-colors hover:text-foreground hover:underline disabled:cursor-default disabled:opacity-60 disabled:hover:no-underline";

export default function QrInvoiceView({
  orderId,
  initial = null,
  pkg = null,
  deviceKey,
  returnTo,
  fullPrice = false,
  onPaid,
  onOtherMethod,
  onClose,
}: Props) {
  const { t } = useTranslation("qrpay", { useSuspense: false });
  const { invoice, secondsLeft, polling, stale, notFound, refresh, replace } = useQrInvoice(orderId, {
    initial,
    onPaid: (paid) => onPaid?.(paid),
  });

  // Окно открывается только в браузере (модалка на сервере не рисуется), так
  // что платформу можно прочитать сразу — без кадра с «чужой» раскладкой.
  const [env, setEnv] = useState<QrEnv>(readEnv);
  useEffect(() => {
    const apply = () =>
      setEnv((prev) => {
        const next = readEnv();
        return prev.platform === next.platform && prev.embed === next.embed && prev.mobile === next.mobile
          ? prev
          : next;
      });
    // Скрипт Telegram мог догрузиться уже после первого рендера.
    apply();
    let mq: MediaQueryList | null = null;
    try {
      mq = window.matchMedia?.("(pointer: coarse)") ?? null;
      mq?.addEventListener?.("change", apply);
    } catch {
      mq = null;
    }
    return () => {
      try {
        mq?.removeEventListener?.("change", apply);
      } catch {
        // старый браузер без addEventListener у MediaQueryList
      }
    };
  }, []);

  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const [saveState, setSaveState] = useState<"idle" | "saving" | "failed">("idle");
  // idle → sending → (hold 30 с → armed) : см. onOther.
  const [cancelPhase, setCancelPhase] = useState<QrCancelPhase>("idle");
  const [actionError, setActionError] = useState("");
  const [creating, setCreating] = useState(false);
  // Скидка закреплена за начатой оплатой картой — выход один: к выбору способа.
  const [createHeld, setCreateHeld] = useState(false);
  const [redirectIn, setRedirectIn] = useState(3);

  const qrWrapRef = useRef<HTMLDivElement>(null);
  const prepared = useRef<{ data: string; blob: Blob } | null>(null);
  const holdTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const shown = useRef<{ order: string; at: number } | null>(null);
  const paidSent = useRef<string | null>(null);
  const expiredSent = useRef<string | null>(null);

  useEffect(
    () => () => {
      if (holdTimer.current) clearTimeout(holdTimer.current);
    },
    []
  );

  const state: QrUiState | "loading" | "error" = notFound ? "error" : invoice ? invoice.ui_state : "loading";
  const currentOrder = invoice?.order_id || orderId;
  const packageId = invoice?.package.id ?? pkg?.id ?? null;
  const packageName = invoice?.package.name || pkg?.name || "";
  const qrData = invoice?.qr.data || "";
  const isTest = Boolean(invoice?.is_test);
  const resumed = Boolean(invoice?.resumed);

  // --- воронка: показан / увидел «оплачено» / истёк -------------------------
  useEffect(() => {
    if (state === "loading" || state === "error") return;
    if (state === "awaiting_payment" && shown.current?.order !== currentOrder) {
      shown.current = { order: currentOrder, at: Date.now() };
      trackFunnel("kgs_qr_shown", {
        package_id: packageId,
        resumed,
        mobile: env.mobile,
        embed: env.embed,
        is_test: isTest,
      });
    }
    if (state === "paid" && paidSent.current !== currentOrder) {
      paidSent.current = currentOrder;
      const since = shown.current?.order === currentOrder ? shown.current.at : null;
      trackFunnel("kgs_qr_paid", {
        package_id: packageId,
        seconds: since === null ? null : Math.max(0, Math.round((Date.now() - since) / 1000)),
      });
    }
    if (state === "expired" && expiredSent.current !== currentOrder) {
      expiredSent.current = currentOrder;
      trackFunnel("kgs_qr_expired", { package_id: packageId });
    }
  }, [state, currentOrder, packageId, resumed, isTest, env.mobile, env.embed]);

  // --- iOS: картинку QR готовим заранее -------------------------------------
  // Окно «сохранить» Safari открывает только по живому нажатию; если после
  // нажатия ещё рисовать PNG, жест может «протухнуть».
  useEffect(() => {
    if (state !== "awaiting_payment" || !qrData || env.platform !== "ios" || env.embed !== "browser") return;
    if (prepared.current?.data === qrData) return;
    let cancelled = false;
    void renderQrPng(qrWrapRef.current).then((blob) => {
      if (!cancelled && blob) prepared.current = { data: qrData, blob };
    });
    return () => {
      cancelled = true;
    };
  }, [state, qrData, env.platform, env.embed]);

  // --- возврат после оплаты (студия, чат): как у крипты ---------------------
  useEffect(() => {
    if (state !== "paid" || !returnTo) return;
    let left = 3;
    const id = setInterval(() => {
      left -= 1;
      setRedirectIn(Math.max(0, left));
      if (left <= 0) {
        clearInterval(id);
        window.location.assign(returnTo);
      }
    }, 1000);
    return () => clearInterval(id);
  }, [state, returnTo]);

  const som = t("topup.som", { ns: "common", defaultValue: "сом" });
  const money = (value: string | null | undefined): string => {
    if (!value) return "";
    if (invoice && invoice.currency && invoice.currency !== "KGS") return `${value} ${invoice.currency}`;
    return formatPrice(Number(value) || 0, "KGS", som);
  };

  /** Уйти с этого QR к выбору способа (или просто закрыть окно). */
  const leave = () => {
    clearQrSession(currentOrder);
    if (onOtherMethod) onOtherMethod();
    else onClose();
  };

  const onSave = async () => {
    if (!invoice || saveState === "saving") return;
    setSaveState("saving");
    const ready = prepared.current?.data === invoice.qr.data ? prepared.current.blob : null;
    const ok = await saveQrImage(qrWrapRef.current, qrFileName(invoice.order_id), env.platform, env.embed, ready);
    trackFunnel("kgs_qr_save", { package_id: packageId, ok });
    if (!alive.current) return;
    setSaveState(ok ? "idle" : "failed");
  };

  const onOther = async () => {
    if (!invoice) return;
    // Состояние счёта — раньше паузы: счёт мог закрыться (истёк, банк отказал),
    // пока шла пауза «банк обрабатывает оплату», и кнопка на экране закрытого
    // счёта иначе молчала бы до её конца.
    const step = otherMethodStep(invoice.ui_state, cancelPhase);
    if (step === "wait") return;
    trackFunnel("kgs_qr_other_method", { package_id: packageId });
    // Закрытый счёт отменять незачем — сразу к выбору способа.
    if (step === "leave") {
      leave();
      return;
    }
    // Второе нажатие после паузы: банк так и не подтвердил оплату — уходим,
    // QR остаётся «брошенным» (сервер продолжит его закрывать).
    const abandon = step === "abandon";
    setCancelPhase("sending");
    setActionError("");
    const res = await fetchData<QrCancelResult>(
      `plans/purchase/qr/${encodeURIComponent(invoice.order_id)}/cancel/`,
      "POST",
      abandon ? { abandon: true } : null,
      true
    );
    if (!alive.current) return;
    const data = res.ok ? res.data : null;
    if (data && typeof data.released === "boolean") {
      if (data.released) {
        setCancelPhase("idle");
        leave();
        return;
      }
      if (data.result === "busy") {
        // Банк прямо сейчас проводит оплату по этому QR. Уйти отсюда на карту —
        // значит заплатить второй раз, а возврата через API нет. Остаёмся,
        // опрашиваем, и только через полминуты снова даём уйти.
        setCancelPhase("hold");
        if (holdTimer.current) clearTimeout(holdTimer.current);
        holdTimer.current = setTimeout(() => {
          setCancelPhase((phase) => (phase === "hold" ? "armed" : phase));
        }, CANCEL_HOLD_MS);
        refresh();
        return;
      }
      // committed: QR оплачен — экран сам покажет «оплачено» / «зачисляем».
      setCancelPhase("idle");
      refresh();
      return;
    }
    if (res.status === 404) {
      setCancelPhase("idle");
      refresh();
      return;
    }
    setCancelPhase(abandon ? "armed" : "idle");
    setActionError(t("err_generic", { defaultValue: "Не удалось выполнить действие. Попробуйте ещё раз." }));
  };

  const onNewQr = async () => {
    if (packageId == null || creating) return;
    setCreating(true);
    setActionError("");
    setCreateHeld(false);
    const res = await fetchData<QrInvoice>(
      "plans/purchase/",
      "POST",
      {
        package_id: packageId,
        pay_currency: "KGS",
        method: "elqr",
        ...(fullPrice ? { full_price: true } : {}),
        ...(returnTo ? { return_to: returnTo } : {}),
      },
      true,
      deviceKey ? { "X-Device-Key": deviceKey } : undefined
    );
    if (!alive.current) return;
    setCreating(false);
    if (res.ok && isQrInvoice(res.data)) {
      saveQrSession({ order_id: res.data.order_id, package_name: packageName || undefined });
      if (holdTimer.current) clearTimeout(holdTimer.current);
      setSaveState("idle");
      setCancelPhase("idle");
      replace(res.data);
      return;
    }
    const code = res.error || "";
    if (code === "qr_too_often") {
      setActionError(
        t("err_too_often", { defaultValue: "Слишком много попыток — подождите минуту и попробуйте снова." })
      );
    } else if (code === "qr_busy") {
      setActionError(
        t("err_busy", {
          defaultValue: "Проверяем вашу предыдущую оплату по QR — повторите через несколько секунд.",
        })
      );
    } else if (code === "qr_too_many_open_invoices") {
      setActionError(
        t("err_too_many", {
          defaultValue: "Слишком много открытых QR-кодов. Подождите несколько минут и попробуйте снова.",
        })
      );
    } else if (res.status === 409 && code === "discount_held") {
      setCreateHeld(true);
      setActionError(
        t("err_discount_held", {
          defaultValue: "Скидка закреплена за другой начатой оплатой. Вернитесь к выбору способа.",
        })
      );
    } else if (res.status === 502 || code === "method_unavailable") {
      setActionError(
        t("err_unavailable", {
          defaultValue: "Оплата по QR сейчас недоступна. Попробуйте позже или выберите другой способ.",
        })
      );
    } else {
      setActionError(t("err_generic", { defaultValue: "Не удалось выполнить действие. Попробуйте ещё раз." }));
    }
  };

  const errorLine = actionError ? (
    <div
      role="alert"
      className="w-full rounded-xl border border-status-fail/40 bg-status-fail/10 px-3 py-2 text-left text-sm text-foreground"
    >
      {actionError}
    </div>
  ) : null;

  const newQrButton =
    packageId != null ? (
      <button type="button" onClick={() => void onNewQr()} disabled={creating} className={BTN_PRIMARY}>
        {creating && <FiLoader className="animate-spin" />}
        {t("new_qr", { defaultValue: "Создать новый QR-код" })}
      </button>
    ) : null;

  const closeButton = (
    <button type="button" onClick={onClose} className={BTN_SECONDARY}>
      {t("close", { defaultValue: "Закрыть" })}
    </button>
  );

  const checkButton = (className: string) => (
    <button type="button" onClick={refresh} disabled={polling} className={className}>
      <FiRefreshCw className={polling ? "animate-spin" : ""} />
      {polling
        ? t("checking", { defaultValue: "Проверяем…" })
        : t("check_now", { defaultValue: "Проверить сейчас" })}
    </button>
  );

  // --- возврат к счёту: данных ещё нет --------------------------------------
  if (state === "loading") {
    return (
      <div className="flex flex-col items-center gap-3 py-10 text-muted">
        <FiLoader className="animate-spin text-2xl" />
        {t("loading", { defaultValue: "Загружаем QR-код…" })}
      </div>
    );
  }

  // --- счёта нет (закрыт, чужой, стёрт) -------------------------------------
  if (state === "error") {
    return (
      <div className="flex flex-col items-center gap-4 py-8 text-center">
        <QrStatusPill state="expired" />
        <p className="max-w-md text-sm text-muted">
          {t("not_found", { defaultValue: "QR-код не найден — возможно, он уже закрыт. Создайте новый." })}
        </p>
        <div className="flex w-full max-w-md flex-col gap-2 sm:flex-row sm:justify-center">
          {newQrButton}
          {closeButton}
        </div>
        {errorLine && <div className="w-full max-w-md">{errorLine}</div>}
      </div>
    );
  }

  // Дальше счёт точно есть: loading и error разобраны выше.
  if (!invoice) return null;

  const credits = invoice.credits.credited || invoice.credits.total || invoice.package.tokens;
  const bonus = Number(invoice.package.bonus_tokens || pkg?.bonus_tokens || 0);

  // --- оплачено --------------------------------------------------------------
  if (state === "paid") {
    return (
      <div className="flex flex-col items-center gap-4 py-8 text-center">
        <FiCheckCircle className="text-5xl text-status-ok motion-safe:animate-[pop_.3s_ease-out]" />
        <div className="text-xl font-semibold text-foreground" role="status">
          {t("paid_title", { defaultValue: "Оплата получена" })}
        </div>
        <div className="text-sm text-muted">
          {t("credits_added", {
            credits: credits.toLocaleString("ru-RU"),
            defaultValue: "Зачислено кредитов: {{credits}}",
          })}
        </div>
        {packageName && <div className="text-xs text-muted-2">{packageName}</div>}
        <button
          type="button"
          onClick={() => (returnTo ? window.location.assign(returnTo) : onClose())}
          className={`mt-2 ${BTN_PRIMARY}`}
        >
          {returnTo
            ? t("back_to_project", { defaultValue: "Вернуться к работе" })
            : t("done", { defaultValue: "Готово" })}
        </button>
        {returnTo && (
          <div className="text-xs text-muted-2">
            {t("redirecting", { seconds: redirectIn, defaultValue: "Возвращаемся через {{seconds}} с…" })}
          </div>
        )}
      </div>
    );
  }

  // --- деньги пришли, кредиты ещё не зачислены ------------------------------
  if (state === "processing") {
    return (
      <div className="mx-auto flex w-full max-w-md flex-col items-center gap-4 py-6 text-center">
        <QrStatusPill state="processing" />
        <div className="text-xl font-semibold text-foreground">
          {t("processing_title", { defaultValue: "Оплата получена" })}
        </div>
        <p className="text-sm leading-snug text-muted">
          {t("processing_note", {
            defaultValue:
              "Зачисляем кредиты — обычно это занимает до минуты. Если кредиты не появились, напишите в поддержку и назовите номер заказа.",
          })}
        </p>
        <CopyField
          className="w-full text-left"
          label={t("order_label", { defaultValue: "Номер заказа" })}
          value={invoice.order_id}
        />
        <div className="flex w-full flex-col gap-2 sm:flex-row sm:justify-center">
          {checkButton(BTN_SECONDARY)}
          {closeButton}
        </div>
        <p className="text-[11px] leading-snug text-muted-2">
          {stale
            ? t("connection_retry", { defaultValue: "Нет связи с сервером, повторяем…" })
            : t("auto_note", {
                defaultValue:
                  "Кредиты зачислятся автоматически сразу после оплаты. Окно можно закрыть — оплата сохранится.",
              })}
        </p>
      </div>
    );
  }

  // --- QR закрыт: истёк, отменён, платёж не прошёл --------------------------
  if (state === "expired" || state === "cancelled" || state === "failed") {
    const title =
      state === "expired"
        ? t("expired_title", { defaultValue: "Время QR-кода истекло" })
        : state === "cancelled"
          ? t("cancelled_title", { defaultValue: "Оплата по этому QR отменена" })
          : t("failed_title", { defaultValue: "Платёж не прошёл" });
    const note =
      state === "expired"
        ? t("expired_note", {
            defaultValue:
              "Если вы уже оплатили — кредиты зачислятся автоматически. Иначе создайте новый QR-код.",
          })
        : state === "failed"
          ? t("failed_note", {
              defaultValue: "Банк отклонил платёж. Создайте новый QR-код или выберите другой способ оплаты.",
            })
          : "";
    return (
      <div className="mx-auto flex w-full max-w-md flex-col items-center gap-4 py-6 text-center">
        <QrStatusPill state={state} />
        <div className="text-xl font-semibold text-foreground">{title}</div>
        {note && <p className="text-sm leading-snug text-muted">{note}</p>}
        {packageName && (
          <div className="text-xs text-muted-2">
            {packageName} — {money(invoice.amount)}
          </div>
        )}
        {errorLine}
        <div className="flex w-full flex-col gap-2">
          {!createHeld && newQrButton}
          {(onOtherMethod || createHeld) && (
            <button
              type="button"
              onClick={() => void onOther()}
              className={createHeld ? BTN_PRIMARY : BTN_SECONDARY}
            >
              {t("other_method", { defaultValue: "Оплатить другим способом" })}
            </button>
          )}
          {closeButton}
        </div>
      </div>
    );
  }

  // --- ждём оплату -----------------------------------------------------------
  const checkoutUrl = isHttpsUrl(invoice.checkout_url) ? invoice.checkout_url : "";
  const imageUrl = isHttpsUrl(invoice.qr.image_url) ? invoice.qr.image_url : "";
  const otherBusy = cancelPhase === "sending";
  const otherDisabled = otherBusy || cancelPhase === "hold";
  const lowTime = secondsLeft > 0 && secondsLeft <= 60;

  const testStrip = isTest ? (
    <div
      role="note"
      className="flex items-start gap-2 rounded-xl border border-status-fail/50 bg-status-fail/10 px-3 py-2.5 text-sm font-medium leading-snug text-foreground"
    >
      <FiAlertTriangle className="mt-0.5 shrink-0 text-status-fail" />
      {t("test_badge", {
        defaultValue:
          "ТЕСТОВЫЙ ПЛАТЁЖ. QR не предназначен для оплаты, статус сменится сам примерно через 20 секунд.",
      })}
    </div>
  ) : null;

  const header = (
    <div className="flex flex-col gap-3 rounded-2xl border border-border bg-surface-2 p-3.5 sm:p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-base font-semibold text-foreground">{packageName}</div>
          <div className="text-xs text-muted">
            {(invoice.package.tokens || invoice.credits.total).toLocaleString("ru-RU")}{" "}
            {t("topup.credits", { ns: "common", defaultValue: "кредитов" })}
            {bonus > 0 ? ` +${bonus.toLocaleString("ru-RU")}` : ""}
          </div>
        </div>
        <div className="shrink-0 text-right leading-tight">
          <div className="text-[11px] text-muted">{t("amount_title", { defaultValue: "К оплате" })}</div>
          <div className="text-2xl font-bold tabular-nums text-foreground">{money(invoice.amount)}</div>
          {invoice.original_amount && invoice.original_amount !== invoice.amount && (
            <div className="text-xs tabular-nums text-muted line-through">{money(invoice.original_amount)}</div>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
        <QrStatusPill state="awaiting_payment" />
        <div className="text-right leading-tight" role="timer" aria-live="off">
          <div
            className={`text-lg font-semibold tabular-nums ${lowTime ? "text-status-wait" : "text-foreground"}`}
          >
            {secondsLeft > 0 ? formatCountdown(secondsLeft) : "—"}
          </div>
          <div className="text-[10px] text-muted-2">
            {secondsLeft > 0
              ? t("time_left_hint", { defaultValue: "столько действует QR-код" })
              : t("time_over", { defaultValue: "время истекло" })}
          </div>
        </div>
      </div>
    </div>
  );

  const qrTile = (size: number) =>
    qrData ? (
      <div ref={qrWrapRef} className="inline-flex">
        <QrCode value={qrData} size={size} label={t("qr_label", { defaultValue: "QR-код для оплаты" })} />
      </div>
    ) : (
      // Пустую строку в QR не кодируем: получился бы «код», который ничего не
      // оплачивает. Так бывает только у тестового платежа.
      <div
        className="flex items-center justify-center rounded-2xl border border-dashed border-border bg-surface-2 p-4 text-center text-sm leading-snug text-muted"
        style={{ width: size + 24, minHeight: size + 24, maxWidth: "100%" }}
      >
        {isTest
          ? t("test_no_qr", { defaultValue: "Тестовый платёж: GoPay не прислал QR-код. Статус сменится сам." })
          : t("err_unavailable", {
              defaultValue: "Оплата по QR сейчас недоступна. Попробуйте позже или выберите другой способ.",
            })}
      </div>
    );

  const saveButton = qrData ? (
    <button type="button" onClick={() => void onSave()} disabled={saveState === "saving"} className={BTN_SECONDARY}>
      {saveState === "saving" ? <FiLoader className="animate-spin" /> : <FiDownload />}
      {t("save_qr", { defaultValue: "Сохранить QR-код" })}
    </button>
  ) : null;

  // Сохранить не вышло — не молчим: говорим об этом и даём картинку открыть.
  const saveFailed =
    saveState === "failed" ? (
      <div
        role="status"
        className="flex flex-col gap-2 rounded-xl border border-status-wait/30 bg-status-wait/10 px-3 py-2 text-left text-xs leading-snug text-foreground"
      >
        {t("save_failed", {
          defaultValue:
            "Не получилось сохранить автоматически. Откройте картинку и сохраните её долгим нажатием.",
        })}
        {imageUrl && (
          <a
            href={imageUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 self-start text-sm font-medium text-foreground underline underline-offset-4"
          >
            <FiExternalLink className="shrink-0" />
            {t("open_qr_image", { defaultValue: "Открыть QR-картинку" })}
          </a>
        )}
      </div>
    ) : null;

  const otherButton = (
    <button type="button" onClick={() => void onOther()} disabled={otherDisabled} className={BTN_LINK}>
      {otherBusy && <FiLoader className="animate-spin" />}
      {t("other_method", { defaultValue: "Оплатить другим способом" })}
    </button>
  );

  const cancelBusyNote =
    cancelPhase === "hold" ? (
      <div
        role="status"
        className="rounded-xl border border-status-wait/30 bg-status-wait/10 px-3 py-2 text-left text-sm leading-snug text-foreground"
      >
        {t("cancel_busy", {
          defaultValue: "Банк уже обрабатывает оплату по этому QR. Проверяем — подождите несколько секунд.",
        })}
      </div>
    ) : null;

  const footer = (
    <p className="border-t border-border pt-3 text-[11px] leading-snug text-muted-2" aria-live="polite">
      {stale
        ? t("connection_retry", { defaultValue: "Нет связи с сервером, повторяем…" })
        : t("auto_note", {
            defaultValue:
              "Кредиты зачислятся автоматически сразу после оплаты. Окно можно закрыть — оплата сохранится.",
          })}
    </p>
  );

  // ------------------------------------------------------------ телефон
  if (env.mobile) {
    // Встроенный браузер (Telegram, Instagram, Facebook): ссылку со своей
    // схемой он может проглотить или заменить нашу страницу ошибкой, файл не
    // скачать, новое окно не открыть. Выход — страница оплаты в настоящем
    // браузере и ссылка, которую всегда можно скопировать.
    const showEmbedExit = env.embed !== "browser" && Boolean(checkoutUrl) && !isTest;
    const openInBrowser = (e: React.MouseEvent<HTMLAnchorElement>) => {
      if (env.embed !== "tg_miniapp") return;
      try {
        const webApp = (window as unknown as TelegramHost).Telegram?.WebApp;
        if (webApp && typeof webApp.openLink === "function") {
          // Mini App: openLink открывает системный браузер, а не webview.
          webApp.openLink(checkoutUrl);
          e.preventDefault();
        }
      } catch {
        // метода нет или он упал — сработает сама ссылка
      }
    };
    return (
      <div className="mx-auto flex w-full max-w-md flex-col gap-4">
        {testStrip}
        {header}

        {showEmbedExit && (
          <section className="flex flex-col gap-2.5 rounded-2xl border border-accent/50 bg-accent/5 p-3.5">
            <p className="text-sm leading-snug text-foreground">
              {t("inapp_hint", {
                defaultValue:
                  "Вы открыли сайт внутри другого приложения — кнопки банков здесь могут не сработать. Откройте страницу оплаты в браузере или скопируйте ссылку.",
              })}
            </p>
            <a
              href={checkoutUrl}
              target="_blank"
              rel="noopener noreferrer"
              onClick={openInBrowser}
              className={BTN_PRIMARY}
            >
              <FiExternalLink className="shrink-0" />
              {t("open_in_browser", { defaultValue: "Открыть страницу оплаты в браузере" })}
            </a>
            <CopyField
              label={t("checkout_link_label", { defaultValue: "Ссылка на оплату" })}
              value={checkoutUrl}
            />
          </section>
        )}

        {/* Тестовый QR не оплатить — кнопки банков только сбили бы с толку. */}
        {!isTest && (
          <QrBankApps
            apps={invoice.apps}
            platform={env.platform}
            checkoutUrl={checkoutUrl}
            packageId={packageId}
          />
        )}

        <div className="flex flex-col items-center gap-2.5">
          {qrTile(208)}
          {saveButton && <div className="flex w-full flex-col">{saveButton}</div>}
          {saveButton && (
            <p className="text-center text-xs leading-snug text-muted">
              {t("save_hint", {
                defaultValue: "Сохранённый QR можно загрузить в приложении банка из галереи или из загрузок.",
              })}
            </p>
          )}
          {saveFailed && <div className="w-full">{saveFailed}</div>}
        </div>

        {cancelBusyNote}
        {errorLine}
        <div className="flex flex-col gap-1">
          {checkButton(BTN_SECONDARY)}
          {otherButton}
        </div>
        {footer}
      </div>
    );
  }

  // ---------------------------------------------------------- компьютер
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      {testStrip}
      {header}
      <div className="grid gap-5 md:grid-cols-[auto_minmax(0,1fr)] md:items-start">
        <div className="flex flex-col items-center gap-2">
          {qrTile(232)}
          <p className="max-w-[256px] text-center text-xs leading-snug text-muted">
            {t("scan_hint", { defaultValue: "Отсканируйте код в приложении любого банка Кыргызстана" })}
          </p>
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          <ol className="flex flex-col gap-2.5">
            {[
              t("step_1", { defaultValue: "Откройте приложение своего банка" }),
              t("step_2", { defaultValue: "Выберите «Оплата по QR» и наведите камеру на код" }),
              t("step_3", { defaultValue: "Проверьте сумму и подтвердите оплату" }),
            ].map((text, i) => (
              <li key={i} className="flex items-start gap-3 text-sm leading-snug text-foreground">
                <span
                  aria-hidden="true"
                  className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent/15 text-xs font-bold text-accent"
                >
                  {i + 1}
                </span>
                <span className="pt-0.5">{text}</span>
              </li>
            ))}
          </ol>
          <div className="flex flex-wrap gap-2">
            {saveButton}
            {checkButton(BTN_SECONDARY)}
          </div>
          {saveFailed}
          {cancelBusyNote}
          {errorLine}
          <div className="flex justify-start">{otherButton}</div>
        </div>
      </div>
      {footer}
    </div>
  );
}
