"use client";

import { useCallback, useEffect, useRef, type Dispatch } from "react";
import { useTranslation } from "react-i18next";
import { pollTakes } from "@/lib/vstudio/api";
import type { TakeLite, Uid, VsAction } from "@/lib/vstudio/types";
import { TAKES_SETTLED_EVENT, settledToast } from "../feed/feedLogic";
import { createTakePoller, type SettledTake, type TakePoller } from "../feed/takePoller";

export type UseTakePollingOptions = {
  /** Стор дублей: по нему видно, что дубль закрылся именно этим ответом. */
  takes: Map<Uid, TakeLite>;
  dispatch: Dispatch<VsAction>;
  /** После закрытия дублей (уже после takes/upsert): автопрокрутка ленты. */
  onSettled?: (settled: SettledTake[]) => void;
  /** false — не опрашивать (гость, студия выключена). */
  enabled?: boolean;
};

/**
 * useTakePolling(openUids) — живые статусы дублей (§9.4).
 *
 * GET takes/?ids= каждые 3 с (через 2 минуты — каждые 6 с), на скрытой
 * вкладке пауза, при возврате на вкладку и при появлении сети — сразу
 * запрос; открытых дублей нет — опроса нет. Расписание — в takePoller.ts.
 *
 * На закрытие дубля: takes/upsert, событие balance:refresh (списание или
 * снятый резерв видны в шапке), всплывающее уведомление с uid дубля
 * (клик по нему → ui/focusTake) и onSettled для автопрокрутки.
 *
 * Хук один на страницу: его вызывает RunThread для всех открытых дублей
 * стора, в том числе восстановленных из других проектов.
 */
export function useTakePolling(openUids: readonly Uid[], opts: UseTakePollingOptions): { pollNow: () => void } {
  const { takes, dispatch, onSettled, enabled = true } = opts;
  const { t } = useTranslation("vstudio", { useSuspense: false });

  // Поллер живёт дольше рендера: свежие значения читает через ссылки.
  const takesRef = useRef(takes);
  const dispatchRef = useRef(dispatch);
  const settledRef = useRef(onSettled);
  const tRef = useRef(t);
  useEffect(() => {
    takesRef.current = takes;
    dispatchRef.current = dispatch;
    settledRef.current = onSettled;
    tRef.current = t;
  });

  const pollerRef = useRef<TakePoller | null>(null);

  useEffect(() => {
    const poller = createTakePoller({
      poll: (uids) => pollTakes(uids),
      known: (uid) => takesRef.current.get(uid),
      hidden: () => typeof document !== "undefined" && document.visibilityState === "hidden",
      // Сеть и 5xx поллер переживает сам (отступ), 401 — пауза до нового
      // дубля (вход проверит контейнер). Студию выключили флагом посреди
      // работы — та же страница «скоро откроется», что и у остальных запросов.
      onError: (error) => {
        if (error.code === "vstudio_disabled") dispatchRef.current({ type: "page/status", status: "disabled" });
      },
      onItems: (items, settled) => {
        const send = dispatchRef.current;
        send({ type: "takes/upsert", takes: items });
        if (!settled.length) return;
        // Списание (done) или снятый резерв (failed/lost) меняют баланс в шапке.
        try {
          window.dispatchEvent(new CustomEvent("balance:refresh"));
        } catch {
          /* без события баланс обновится при следующем заходе */
        }
        const tr = tRef.current;
        for (const { take } of settled) {
          const toast = settledToast(take);
          if (!toast) continue;
          send({
            type: "ui/toast",
            toast: {
              id: toast.id,
              tone: toast.tone,
              text: tr(toast.phrase.key, { defaultValue: toast.phrase.ru, ...(toast.phrase.params || {}) }),
              take: take.uid,
            },
          });
        }
        try {
          window.dispatchEvent(
            new CustomEvent(TAKES_SETTLED_EVENT, { detail: settled.map(({ take }) => ({ uid: take.uid, shot: take.shot })) }),
          );
        } catch {
          /* без события «Идёт генерация» в «Истории» обновится при следующей загрузке */
        }
        settledRef.current?.(settled);
      },
    });
    pollerRef.current = poller;

    const onVisible = () => {
      if (document.visibilityState === "visible") poller.wake();
    };
    const onOnline = () => poller.wake();
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", onOnline);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onOnline);
      poller.stop();
      if (pollerRef.current === poller) pollerRef.current = null;
    };
  }, []);

  // Стабильный ключ набора: опрос перестраивается, только когда набор изменился.
  const key = enabled ? Array.from(new Set(openUids)).sort().join(",") : "";
  useEffect(() => {
    pollerRef.current?.setOpen(key ? key.split(",") : []);
  }, [key]);

  const pollNow = useCallback(() => pollerRef.current?.wake(), []);
  return { pollNow };
}
