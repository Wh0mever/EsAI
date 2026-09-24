"use client";

/**
 * Видеостудия: цена и проверки на кнопке «Создать» (§9.4 useQuote).
 *
 * quote/ — тот же компилятор, что и запуск: цена, ошибки и предупреждения,
 * счётчик длины. Когда спрашивать:
 *  - модель, параметры, лоток, статус материала («создаётся» → готово) — сразу;
 *  - текст — после паузы 700 мс (§9.4);
 *  - устаревший запрос отменяет AbortController, а редьюсер к тому же
 *    выбрасывает ответ, чей key уже не совпадает с телом (quote/loaded).
 *
 * key в сторе — quoteKey(тело). Запуск берёт цену только из quote с тем же
 * key: «Создать · 164 кр» всегда про то, что уйдёт. В запасной textarea тело
 * несёт prompt_text вместо prompt_doc (теги разберёт сервер).
 *
 * useQuote — для композера (пишет в стор, его цену видят панель параметров
 * и кнопка); useLocalQuote — для мини-окна «Создать картинку» (своё тело,
 * стор не трогает).
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { quote as quoteApi, quoteBodyFrom, quoteKey } from "@/lib/vstudio/api";
import { isAborted } from "@/lib/vstudio/errors";
import type { QuoteBody, QuoteJSON, VsError, VsResult } from "@/lib/vstudio/types";
import { useVStudio } from "../context";
import {
  countOpen,
  quoteDelay,
  statusSignature,
  structureKey,
  withPromptText,
  type QuoteTrigger,
} from "../composer/composerLogic";

export { withPromptText };

export type UseQuoteOptions = {
  /** Не null — работает запасная textarea: отправлять prompt_text. */
  promptText?: string | null;
  /** false — не спрашивать (студия закрыта, композер скрыт). */
  enabled?: boolean;
};

export type UseQuote = {
  /** Тело запроса ровно как уйдёт в quote/ и shots/ (null — модель не выбрана). */
  body: QuoteBody | null;
  key: string;
  /** quote, который годится для запуска (key и статусы материалов совпали). */
  fresh: QuoteJSON | null;
  loading: boolean;
  error: VsError | null;
  /** Последняя цена при той же структуре (меняется только текст) — показывать приглушённо. */
  lastCredits: number | null;
  /**
   * Последний ответ при той же структуре — пока текст пересчитывается, подсказки
   * не мигают. Для запуска не годится (только fresh).
   */
  last: QuoteJSON | null;
  /** Спросить заново сейчас (после 409 price_changed или 422 blocked). */
  refresh: () => void;
  /**
   * Свежая цена для запуска: сразу, если есть; иначе — запрос без паузы.
   * null — тело пустое или запрос устарел, пока ждали.
   */
  ensureFresh: () => Promise<VsResult<QuoteJSON> | null>;
};

type Done = { structure: string; extra: string };

export function useQuote(opts: UseQuoteOptions = {}): UseQuote {
  const { state, dispatch, authed } = useVStudio();
  const { composer, project, takes, quote } = state;

  const body = useMemo(
    () => withPromptText(quoteBodyFrom(composer, project?.uid ?? null), opts.promptText),
    [composer, project?.uid, opts.promptText],
  );
  const key = useMemo(() => quoteKey(body), [body]);
  const structure = useMemo(() => structureKey(body), [body]);
  const openVideo = countOpen(takes.values(), "video");
  const openImage = countOpen(takes.values(), "image");
  // Статусы материалов и число идущих генераций в тело не входят, но меняют
  // ответ (asset_not_ready, баланс «ждут результата») — по ним тоже пересчёт.
  const extra = `${statusSignature(composer)}|${openVideo}/${openImage}`;
  // Гость спрашивает цену только без материалов (§8.1), иначе 401 и окно входа посреди набора.
  const enabled = opts.enabled !== false && Boolean(body) && (authed !== false || (body?.inputs.length ?? 0) === 0);

  const [done, setDone] = useState<Done | null>(null);

  const live = useRef({ body, key, structure, extra, enabled, quote });
  useLayoutEffect(() => {
    live.current = { body, key, structure, extra, enabled, quote };
  });

  const scheduled = useRef<QuoteTrigger | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const ctl = useRef<AbortController | null>(null);
  const inflight = useRef<{ trigger: QuoteTrigger; promise: Promise<VsResult<QuoteJSON> | null> } | null>(null);

  const clearTimer = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };

  const send = useCallback(
    (trigger: QuoteTrigger, payload: QuoteBody): Promise<VsResult<QuoteJSON> | null> => {
      ctl.current?.abort();
      const controller = new AbortController();
      ctl.current = controller;
      dispatch({ type: "quote/loading", key: trigger.key });
      const promise = quoteApi(payload, { signal: controller.signal }).then((res) => {
        if (controller.signal.aborted || (!res.ok && isAborted(res.error))) return null;
        if (ctl.current === controller) ctl.current = null;
        if (res.ok) dispatch({ type: "quote/loaded", key: trigger.key, quote: res.data });
        else dispatch({ type: "quote/failed", key: trigger.key, error: res.error });
        setDone({ structure: trigger.structure, extra: trigger.extra });
        return res;
      });
      inflight.current = { trigger, promise };
      return promise;
    },
    [dispatch],
  );

  // Расписание: сразу при смене структуры, с паузой — при наборе текста.
  useEffect(() => {
    if (!enabled || !body) {
      clearTimer();
      ctl.current?.abort();
      ctl.current = null;
      scheduled.current = null;
      return;
    }
    const trigger: QuoteTrigger = { key, structure, extra };
    const delay = quoteDelay(scheduled.current, trigger);
    if (delay === null) return;
    scheduled.current = trigger;
    clearTimer();
    if (delay === 0) {
      void send(trigger, body);
      return;
    }
    timer.current = setTimeout(() => {
      timer.current = null;
      const cur = live.current;
      if (cur.enabled && cur.body && cur.key === trigger.key) void send(trigger, cur.body);
    }, delay);
  }, [enabled, body, key, structure, extra, send]);

  useEffect(
    () => () => {
      clearTimer();
      ctl.current?.abort();
      ctl.current = null;
      inflight.current = null;
      // Повторный монтаж (StrictMode, возврат композера) должен спросить цену заново.
      scheduled.current = null;
    },
    [],
  );

  const fresh =
    quote.status === "ready" && quote.key === key && quote.data && done?.extra === extra && done?.structure === structure
      ? quote.data
      : null;
  const last = quote.data && done?.structure === structure ? quote.data : null;
  const lastCredits = last && typeof last.credits === "number" ? last.credits : null;
  const error = quote.status === "error" && quote.key === key ? quote.error : null;
  const loading = enabled && !fresh && !error;

  const refresh = useCallback(() => {
    const cur = live.current;
    if (!cur.enabled || !cur.body) return;
    clearTimer();
    const trigger = { key: cur.key, structure: cur.structure, extra: cur.extra };
    scheduled.current = trigger;
    void send(trigger, cur.body);
  }, [send]);

  const ensureFresh = useCallback(async (): Promise<VsResult<QuoteJSON> | null> => {
    const cur = live.current;
    if (!cur.body) return null;
    const trigger = { key: cur.key, structure: cur.structure, extra: cur.extra };
    const q = cur.quote;
    if (q.status === "ready" && q.key === cur.key && q.data && done?.extra === cur.extra) {
      return { ok: true, status: 200, data: q.data };
    }
    const running = inflight.current;
    if (running && running.trigger.key === trigger.key && running.trigger.extra === trigger.extra) {
      return running.promise;
    }
    clearTimer();
    scheduled.current = trigger;
    const res = await send(trigger, cur.body);
    // Пока ждали, человек успел поменять запрос — эта цена уже не про него.
    return live.current.key === trigger.key ? res : null;
  }, [send, done]);

  return { body, key, fresh, loading, error, lastCredits, last, refresh, ensureFresh };
}

/* ------------------------------------------------------------------ */
/* Своё тело — мини-окно «Создать картинку»                            */
/* ------------------------------------------------------------------ */

export type LocalQuote = {
  data: QuoteJSON | null;
  loading: boolean;
  error: VsError | null;
  refresh: () => void;
};

/** Цена отдельного тела (не пишет в стор). Текст — с паузой, остальное — сразу. */
export function useLocalQuote(body: QuoteBody | null, enabled: boolean): LocalQuote {
  const key = useMemo(() => quoteKey(body), [body]);
  const structure = useMemo(() => structureKey(body), [body]);
  const [result, setResult] = useState<{ key: string; data: QuoteJSON | null; error: VsError | null } | null>(null);
  const [nonce, setNonce] = useState(0);
  const scheduled = useRef<QuoteTrigger | null>(null);
  /** key последнего пришедшего ответа: отменённый запрос с тем же телом надо повторить. */
  const answered = useRef<string | null>(null);
  const bodyRef = useRef(body);
  useLayoutEffect(() => {
    bodyRef.current = body;
  });

  useEffect(() => {
    if (!enabled || !body) {
      scheduled.current = null;
      return;
    }
    const trigger: QuoteTrigger = { key, structure, extra: String(nonce) };
    let delay = quoteDelay(scheduled.current, trigger);
    if (delay === null) {
      if (answered.current === key) return;
      delay = 0;
    }
    scheduled.current = trigger;
    const controller = new AbortController();
    const id = setTimeout(() => {
      const payload = bodyRef.current;
      if (!payload) return;
      void quoteApi(payload, { signal: controller.signal }).then((res) => {
        if (controller.signal.aborted || (!res.ok && isAborted(res.error))) return;
        answered.current = key;
        setResult(res.ok ? { key, data: res.data, error: null } : { key, data: null, error: res.error });
      });
    }, delay);
    return () => {
      clearTimeout(id);
      controller.abort();
    };
  }, [enabled, body, key, structure, nonce]);

  const mine = result && result.key === key ? result : null;
  return {
    data: mine?.data ?? null,
    loading: enabled && Boolean(body) && !mine,
    error: mine?.error ?? null,
    refresh: () => setNonce((n) => n + 1),
  };
}
