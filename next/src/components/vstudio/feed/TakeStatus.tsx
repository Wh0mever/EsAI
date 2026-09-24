"use client";

import { memo, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { FiBell, FiCheck, FiClock, FiLoader, FiX } from "react-icons/fi";
import { enablePush, pushPermission, pushSupported } from "@/tools/webPush";
import type { TakeLite } from "@/lib/vstudio/types";
import { etaPhrase, formatClock, isSlow, liveElapsed, progressShare, statusPhrase } from "./feedLogic";

/* ------------------------------------------------------------------ */
/* Общие часы: один setInterval на всю ленту, а не по одному на дубль   */
/* ------------------------------------------------------------------ */

const clock = {
  now: 0,
  timer: null as ReturnType<typeof setInterval> | null,
  subs: new Set<() => void>(),
};

function subscribeClock(cb: () => void): () => void {
  clock.subs.add(cb);
  if (!clock.timer) {
    clock.now = Date.now();
    clock.timer = setInterval(() => {
      clock.now = Date.now();
      clock.subs.forEach((f) => f());
    }, 1000);
  }
  return () => {
    clock.subs.delete(cb);
    if (!clock.subs.size && clock.timer) {
      clearInterval(clock.timer);
      clock.timer = null;
      // Остановленные часы не должны отдать новому секундомеру время
      // многоминутной давности: следующий readClock возьмёт свежее.
      clock.now = 0;
    }
  };
}

const subscribeNever = () => () => {};
const readClock = () => {
  if (!clock.now) clock.now = Date.now();
  return clock.now;
};
const serverClock = () => 0;

/** Текущее время, мс; тикает раз в секунду только пока active. На сервере — 0. */
export function useNow(active: boolean): number {
  return useSyncExternalStore(active ? subscribeClock : subscribeNever, readClock, serverClock);
}

/**
 * Секундомер дубля от серверного elapsed_s: каждый ответ опроса даёт новую
 * опору, между ответами досчитываем по своим часам. Часы телефона при этом
 * не важны — берётся только разница.
 */
export function useTakeElapsed(take: Pick<TakeLite, "elapsed_s">, active: boolean): number {
  const now = useNow(active);
  const [anchor, setAnchor] = useState({ s: take.elapsed_s, at: now });
  if (anchor.s !== take.elapsed_s) setAnchor({ s: take.elapsed_s, at: now });
  const at = anchor.s === take.elapsed_s ? anchor.at : now;
  return Math.max(take.elapsed_s || 0, liveElapsed(take.elapsed_s, at, now));
}

/* ------------------------------------------------------------------ */

export type TakeStatusProps = {
  take: TakeLite;
  /** «Отменить» — только из queued (дальше сервер ответит already_submitted). */
  onCancel?: () => void;
  canceling?: boolean;
};

/**
 * Идущий дубль (§9.6): «В очереди · вы 2-й», «Отправляем модели…»,
 * «Снимается · 1:24 · обычно ~2 мин», «Сохраняем…». После 1.5×ETA —
 * «Дольше обычного — можно закрыть вкладку, пришлём уведомление» и, если
 * браузер ещё не спрашивали, кнопка включения уведомлений.
 *
 * Живой регион (aria-live) держит TakeView: он переживает смену статуса,
 * а секундомер в него не попадает, чтобы экранный диктор не читал каждую секунду.
 */
function TakeStatus({ take, onCancel, canceling }: TakeStatusProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const elapsed = useTakeElapsed(take, true);
  const [push, setPush] = useState<"idle" | "busy" | "on" | "hidden">("idle");

  const phrase = statusPhrase(take);
  const label = t(phrase.key, { defaultValue: phrase.ru, ...(phrase.params || {}) });
  const eta = etaPhrase(take.eta_s);
  const etaText = eta
    ? t("run.status.eta", {
        defaultValue: "обычно ~{{time}}",
        time: t(eta.key, { defaultValue: eta.ru, ...(eta.params || {}) }),
      })
    : "";
  const slow = take.status !== "queued" && isSlow(elapsed, take.eta_s);
  const share = progressShare(elapsed, take.eta_s);
  // Длинное видео: сразу сказать, что ждать у экрана не обязательно.
  const longRun = take.kind === "video" && take.eta_s >= 60;
  const canAskPush = slow && push !== "hidden" && pushSupported() && pushPermission() === "default";

  const askPush = async () => {
    if (push === "busy") return;
    setPush("busy");
    const res = await enablePush();
    setPush(res === "granted" ? "on" : "hidden");
  };

  return (
    <div className="flex w-full flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
        <FiLoader className="shrink-0 animate-spin text-status-progress" aria-hidden />
        <span className="font-medium text-foreground">{label}</span>
        <span className="tabular-nums text-muted" aria-hidden>
          · {formatClock(elapsed)}
        </span>
        {etaText && !slow && <span className="text-muted">· {etaText}</span>}
        {take.status === "queued" && onCancel && (
          <button
            type="button"
            onClick={onCancel}
            disabled={canceling}
            className="ml-auto inline-flex min-h-9 cursor-pointer items-center gap-1 rounded-lg px-2 text-xs text-muted transition-colors hover:bg-surface-3 hover:text-foreground disabled:cursor-wait disabled:opacity-60"
          >
            {canceling ? <FiLoader className="animate-spin" aria-hidden /> : <FiX aria-hidden />}
            {t("run.actions.cancel", { defaultValue: "Отменить" })}
          </button>
        )}
      </div>

      {share !== null && (
        <div
          className="h-1 w-full overflow-hidden rounded-full bg-surface-3"
          role="progressbar"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(share * 100)}
        >
          <div
            className="h-full rounded-full bg-status-progress transition-[width] duration-1000 ease-linear"
            style={{ width: `${Math.max(3, share * 100)}%` }}
          />
        </div>
      )}

      {slow ? (
        <p className="flex items-start gap-1.5 text-xs text-status-wait">
          <FiClock className="mt-0.5 shrink-0" aria-hidden />
          {t("run.status.slow", {
            defaultValue: "Дольше обычного — можно закрыть вкладку, пришлём уведомление",
          })}
        </p>
      ) : (
        longRun &&
        take.status !== "queued" && (
          <p className="text-xs text-muted-2">
            {t("run.closeTab", { defaultValue: "Можно закрыть вкладку — результат не пропадёт" })}
          </p>
        )
      )}

      {(canAskPush || push === "on") && (
        <div>
          {push === "on" ? (
            <span className="inline-flex items-center gap-1 text-xs text-status-ok">
              <FiCheck aria-hidden />
              {t("run.push.done", { defaultValue: "Уведомления включены" })}
            </span>
          ) : (
            <button
              type="button"
              onClick={() => void askPush()}
              disabled={push === "busy"}
              className="inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-lg border border-border bg-surface px-3 text-xs font-medium text-foreground transition-colors hover:border-accent disabled:cursor-wait disabled:opacity-60"
            >
              {push === "busy" ? <FiLoader className="animate-spin" aria-hidden /> : <FiBell aria-hidden />}
              {t("run.push.enable", { defaultValue: "Прислать уведомление, когда будет готово" })}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default memo(TakeStatus);
