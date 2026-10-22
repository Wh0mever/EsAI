"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { PaywallContext } from "@/components/chat/PaywallModal";
import { isAborted, paywallContext } from "@/lib/vstudio/errors";
import type { VsError } from "@/lib/vstudio/types";
import {
  DEFAULT_AUDIO_LIMITS,
  DEFAULT_AUDIO_PRICES,
  DEFAULT_MUSIC_VOLUME,
  DEFAULT_VOICE_VOLUME,
  afterLostAnswer,
  audioErrorText,
  audioPollDelay,
  audioUploadName,
  cleanText,
  cooldownLeft,
  effectiveStart,
  followStart,
  hasPending,
  isTransportError,
  musicCooldownUntil,
  musicQuote,
  musicRefusal,
  musicSignature,
  orderFailedHere,
  paidSound,
  pickVoice,
  prefillKeepsRetry,
  prefillStep,
  precheckAudio,
  replayedFailure,
  retryMarkFor,
  retryVerdict,
  settingsQueue,
  settleLocal,
  settledTracks,
  soundInfo,
  soundStep,
  trackErrorText,
  trackSlot,
  voicePrice,
  voiceMoveAfterReplay,
  voiceRefusal,
  voiceSignature,
  type FragmentChange,
  type LocalSound,
  type RetryMark,
} from "./audioLogic";
import {
  deleteTrack as deleteTrackApi,
  getAudio,
  listVoices,
  makeMusic as makeMusicApi,
  makeVoice as makeVoiceApi,
  patchAudio,
  uploadMusic as uploadMusicApi,
  type UploadPhase,
} from "./mergeApi";
import { isEditable, refusalText, type LocalItem, type TextSpec } from "./mergeLogic";
import type {
  MergeAudioSettings,
  MergeAudioState,
  MergeAudioSummary,
  MergeBalance,
  MergeClipSound,
  MergeStatus,
  MergeTrack,
  MergeTrackKind,
  MergeVoice,
} from "./mergeTypes";

/**
 * Звук открытой склейки (CONTRACT_M.md §10): голос за кадром, музыка, звук
 * роликов. Состояние приходит с сервера целиком в ответ на каждый запрос.
 *
 * Деньги решает сервер: голос и музыка резервируются при заказе и
 * списываются, только когда звук сохранён; здесь — цена на кнопке (та же
 * формула), 402 → пополнение и request_id на нажатие: повтор после обрыва
 * связи возвращает ту же дорожку и второй раз не списывает.
 *
 * Заказ уходит после сохранения того, что на экране (ensureSaved): длину
 * музыки и номер фрагмента голоса сервер считает по своему списку.
 *
 * Черновики (текст голоса, описание музыки) живут здесь, а не в панели:
 * шторку на телефоне закрыли и открыли — набранное на месте.
 */

const VOICE_KEY = "merge:voice";
/** Ползунок громкости: на сервер — когда палец остановился. */
const VOLUME_DEBOUNCE_MS = 350;
/** Склейка ещё не заведена (первое сохранение впереди) — ключ занятости до него. */
const NEW = "new";

export type AudioUpload = { key: string; name: string; phase: UploadPhase; pct: number };
type Errors = Record<"voice" | "music" | "settings", TextSpec | null>;
type ErrorKind = keyof Errors;
type Draft = { text: string; voiceId: string; start: number; prompt: string };
type VoicesState = { list: MergeVoice[]; loading: boolean; loaded: boolean; failed: boolean };

type Work = { seq: number; inflight: number };

function beginWork(w: Work) {
  w.seq += 1;
  w.inflight += 1;
}

function endWork(w: Work) {
  w.inflight = Math.max(0, w.inflight - 1);
}

const NO_ERRORS: Errors = { voice: null, music: null, settings: null };
const EMPTY_DRAFT: Draft = { text: "", voiceId: "", start: 0, prompt: "" };

function readVoice(): string {
  try {
    return window.localStorage.getItem(VOICE_KEY) || "";
  } catch {
    return "";
  }
}

function rememberVoice(id: string) {
  try {
    window.localStorage.setItem(VOICE_KEY, id);
  } catch {
    /* не запомнили — в следующий раз первый голос списка */
  }
}

export type MergeAudioOptions = {
  /** Открытая склейка; null — новая, ещё не заведена. */
  projectId: string | null;
  status: MergeStatus | null;
  /** ProjectJSON.audio — пока состояние звука не пришло. */
  summary: MergeAudioSummary | null;
  /** Фрагменты на экране: длина музыки и «Начать с фрагмента». */
  items: readonly LocalItem[];
  /** Вход есть и страница загружена. */
  enabled: boolean;
  ensureSaved: () => Promise<string | null>;
  onPaywall: (ctx: PaywallContext) => void;
  onBalance: (b: MergeBalance) => void;
  /** Музыка или голос доделались — баланс изменился. */
  onSettled: () => void;
  /** Сервер поменял статус склейки (неудачная после правки звука — снова черновик). */
  onProjectChanged: () => void;
  /** Склейка, закрытая только на время её удаления: откажет сервер — её звук вернётся как был. */
  parked?: string | null;
  /** У склейки id сейчас ничего не делается (ответ сервера). */
  onIdle?: (id: string) => void;
};

export type MergeAudioModel = ReturnType<typeof useMergeAudio>;

export function useMergeAudio(opts: MergeAudioOptions) {
  const { projectId, status, summary, items, enabled, parked = null } = opts;
  const { t } = useTranslation("vstudio", { useSuspense: false });

  const [audio, setAudio] = useState<{ id: string; state: MergeAudioState } | null>(null);
  const [loadFailed, setLoadFailed] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [voices, setVoices] = useState<VoicesState>({ list: [], loading: false, loaded: false, failed: false });
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [forms, setForms] = useState<Record<MergeTrackKind, boolean>>({ voice: false, music: false });
  const [errors, setErrors] = useState<Errors>(NO_ERRORS);
  const [local, setLocal] = useState<LocalSound>({});
  /** Чей заказ идёт: id склейки (или NEW) — после переключения склейки чужой спиннер не виден. */
  const [voiceBusy, setVoiceBusy] = useState<string | null>(null);
  const [musicBusy, setMusicBusy] = useState<string | null>(null);
  const [upload, setUpload] = useState<AudioUpload | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  /**
   * После music_busy «Создать» ждёт: until — до какого момента (мс), left — сколько секунд
   * осталось (на экране). Места музыки общие на весь сайт — ожидание не привязано к склейке.
   */
  const [musicHold, setMusicHold] = useState<{ until: number; left: number }>({ until: 0, left: 0 });
  /** Что сказать диктору: готово, загружено, удалено. */
  const [said, setSaid] = useState("");

  // Другая склейка — черновики и отказы прежней ей не нужны. Из «новой» в
  // только что заведённую (первое сохранение) — та же склейка: всё остаётся.
  // Склейку закрыли на время её удаления — набранное откладываем: сервер откажет,
  // она откроется снова, и текст голоса с описанием музыки будут на месте.
  const [owner, setOwner] = useState<string | null>(projectId);
  const [kept, setKept] = useState<{ id: string; draft: Draft; forms: Record<MergeTrackKind, boolean> } | null>(null);
  const step = soundStep(owner, projectId, parked, kept?.id ?? null);
  if (step !== "same") {
    setOwner(projectId);
    if (step === "park" || step === "reset") {
      setKept(step === "park" && owner !== null ? { id: owner, draft, forms } : null);
      setDraft((d) => ({ ...EMPTY_DRAFT, voiceId: d.voiceId }));
      setForms({ voice: false, music: false });
      setErrors(NO_ERRORS);
      setLocal({});
    } else if (step === "restore" && kept) {
      setDraft(kept.draft);
      setForms(kept.forms);
      setKept(null);
    } else {
      setKept(null);
    }
  }

  const state = audio && audio.id === projectId ? audio.state : null;

  // Последние значения для асинхронных шагов: ответ сверяется с тем, что на экране сейчас.
  const cb = useRef(opts);
  const draftRef = useRef(draft);
  const localRef = useRef(local);
  const latest = useRef<{ id: string; state: MergeAudioState } | null>(null);
  /** seq растёт с каждым изменением звука: ответ опроса, ушедшего раньше, не затирает новое. */
  const work = useRef<Work>({ seq: 0, inflight: 0 });
  const retry = useRef<Record<"voice" | "music", RetryMark | null>>({ voice: null, music: null });
  /** Чей заказ идёт (id склейки или NEW); null — никакого. */
  const busy = useRef<Record<"voice" | "music", string | null>>({ voice: null, music: null });
  const uploadAbort = useRef<AbortController | null>(null);
  /** Чей свой трек сейчас грузится (id склейки или NEW). */
  const uploadFor = useRef<string | null>(null);
  const sendRef = useRef<(body: MergeAudioSettings) => Promise<boolean>>(async () => false);
  // Правки звука роликов, громкостей и начала голоса — по одной и по порядку; ползунок — когда палец остановился.
  const [settings] = useState(() =>
    settingsQueue<MergeAudioSettings>((body) => sendRef.current(body), {
      set: (fn, ms) => window.setTimeout(fn, ms),
      clear: (handle) => window.clearTimeout(handle as number),
    }),
  );
  const voicesLoading = useRef(false);
  const musicHoldUntil = useRef(0);
  /** Неудачная музыка, чьим описанием уже заполнили форму повтора: второй раз не заполняем. */
  const prefilled = useRef<string | null>(null);

  // Склейка сменилась — метку забываем: вернулись в склейку с той же неудачной музыкой, а
  // черновик при смене опустел — форма повтора снова с её описанием.
  useEffect(() => {
    prefilled.current = null;
  }, [owner]);

  useEffect(() => {
    cb.current = opts;
    draftRef.current = draft;
    localRef.current = local;
  });

  const limits = state?.limits ?? DEFAULT_AUDIO_LIMITS;
  const prices = state?.prices ?? DEFAULT_AUDIO_PRICES;

  const setError = useCallback((kind: ErrorKind, text: TextSpec | null) => {
    setErrors((e) => (e[kind] === text ? e : { ...e, [kind]: text }));
  }, []);

  /** Заказ сделан, хотя ответ на него не дошёл, — как при ответе: форма закрыта, текст убран. */
  const closeOrder = useCallback((kind: MergeTrackKind, upload = false) => {
    setForms((f) => ({ ...f, [kind]: false }));
    if (kind === "voice") {
      setDraft((d) => ({ ...d, text: "" }));
      setLocal((l) => ({ ...l, start: undefined }));
    } else if (!upload) {
      setDraft((d) => ({ ...d, prompt: "" }));
    }
  }, []);

  /**
   * Сервер вернул голос заказа с прежним началом (повтор того же нажатия, а фрагменты с тех пор
   * правили) — двигаем его к выбранному ролику: PATCH бесплатный, заказ второй раз не нужен.
   */
  const placeVoice = useCallback(
    (id: string, s: MergeAudioState, track: MergeTrack | null | undefined) => {
      const cur = cb.current;
      if (id !== cur.projectId) return;
      const to = voiceMoveAfterReplay(track, s.tracks, effectiveStart(draftRef.current.start, cur.items.length));
      if (to === null) return;
      localRef.current = { ...localRef.current, start: to };
      setLocal((l) => ({ ...l, start: to }));
      settings.send({ voice_start_fragment: to });
    },
    [settings],
  );

  /**
   * Метка заказа, ответ на который не дошёл, по звуку склейки (retryVerdict): не вышел именно
   * он — снимаем, следующее нажатие — новый заказ; сделан — снимаем и, если в форме всё тот же
   * заказ, закрываем её, как при ответе (иначе нажатие с тем же текстом заказало бы и списало
   * его второй раз; текст правили — это уже другой заказ). Любое другое состояние id не трогает.
   */
  const settleRetry = useCallback(
    (kind: MergeTrackKind, id: string, s: MergeAudioState, inFlight: boolean) => {
      const held = retry.current[kind];
      const verdict = retryVerdict(held, id, s.tracks, kind, inFlight);
      if (!held || verdict === "keep") return;
      retry.current[kind] = null;
      const cur = cb.current;
      if (verdict !== "done" || id !== cur.projectId) return;
      const d = draftRef.current;
      const sig =
        kind === "voice" ? voiceSignature(d.text, d.voiceId) : musicSignature(d.prompt, musicQuote(s, cur.items)?.seconds ?? 0);
      if (sig !== held.sig) return;
      setError(kind, null);
      closeOrder(kind);
      if (kind === "voice") placeVoice(id, s, s.tracks.find((x) => x.kind === "voice" && x.request_id === held.id));
    },
    [setError, closeOrder, placeVoice],
  );

  /** Ответ сервера — на экран; заодно баланс, доделанные дорожки и статус склейки. */
  const apply = useCallback(
    (id: string, s: MergeAudioState) => {
      const cur = cb.current;
      if (s.balance) cur.onBalance(s.balance);
      // На экран — только звук открытой склейки. Ответ другой (переключились, пока шёл её заказ)
      // занял бы место открытой: она осталась бы на «Загружаю звук…» (MA_V6 B4).
      const open = id === cur.projectId;
      if (open) {
        const prev = latest.current && latest.current.id === id ? latest.current.state : null;
        latest.current = { id, state: s };
        setAudio({ id, state: s });
        setLoadFailed((f) => (f === id ? null : f));
        const done = prev ? settledTracks(prev.tracks, s.tracks) : [];
        if (done.length) {
          cur.onSettled();
          const last = done[done.length - 1];
          if (last.status === "ready") {
            setSaid(
              last.kind === "voice"
                ? t("merge.audio.saidVoice", { defaultValue: "Голос за кадром готов" })
                : t("merge.audio.saidMusic", { defaultValue: "Музыка готова" }),
            );
          } else {
            setSaid(t("merge.audio.saidFailed", { defaultValue: "Звук не получился — кредиты не списаны" }));
          }
        }
      }
      // Метки заказов, ответ на которые не дошёл, — по звуку их склейки (и не открытой тоже).
      for (const kind of ["voice", "music"] as const) settleRetry(kind, id, s, busy.current[kind] !== null);
      // Музыка не сделалась — в форме повтора её описание, а не пустое поле. Пока бережём id
      // заказа, ответ на который не дошёл, — только описание того же заказа (id не сменится).
      const failed = trackSlot(s.tracks, "music").failed;
      if (
        failed &&
        open &&
        failed.id !== prefilled.current &&
        prefillKeepsRetry(retry.current.music, id, failed, musicQuote(s, cur.items)?.seconds ?? 0)
      ) {
        const mark = prefilled.current;
        prefilled.current = failed.id;
        setDraft((d) => {
          const { prompt } = prefillStep(mark, failed, d.prompt);
          return prompt === d.prompt ? d : { ...d, prompt };
        });
      }
      if (open && s.status !== cur.status) cur.onProjectChanged();
      if (!hasPending(s)) cur.onIdle?.(id);
    },
    [t, settleRetry],
  );

  const reload = useCallback(
    async (id: string): Promise<MergeAudioState | null> => {
      const res = await getAudio(id);
      if (!res.ok) return null;
      apply(id, res.data);
      return res.data;
    },
    [apply],
  );

  /* ---------- загрузка и опрос ---------- */

  const editableStatus = isEditable(status);

  useEffect(() => {
    if (!enabled || !projectId || !editableStatus) return;
    let alive = true;
    const started = work.current.seq;
    void getAudio(projectId).then((res) => {
      if (!alive) return;
      if (!res.ok) {
        setLoadFailed(projectId);
        return;
      }
      // Пока шёл запрос, звук поменяли — ответ на изменение новее этого.
      if (started === work.current.seq && work.current.inflight === 0) apply(projectId, res.data);
      else if (!latest.current || latest.current.id !== projectId) apply(projectId, res.data);
    });
    return () => {
      alive = false;
    };
  }, [enabled, projectId, editableStatus, status, reloadKey, apply]);

  // Музыка делается в очереди (а голос — в запросе, который мог оборваться): пока
  // хоть одна дорожка делается — перечитываем; скрытую вкладку не опрашиваем.
  const pendingNow = hasPending(state);
  useEffect(() => {
    if (!pendingNow || !projectId || !enabled) return;
    let alive = true;
    let timer = 0;
    const startedAt = Date.now();
    const next = () => {
      timer = window.setTimeout(tick, audioPollDelay(Date.now() - startedAt));
    };
    const tick = async () => {
      if (document.visibilityState === "hidden") {
        next();
        return;
      }
      const started = work.current.seq;
      const res = await getAudio(projectId);
      if (!alive) return;
      if (res.ok && started === work.current.seq && work.current.inflight === 0) apply(projectId, res.data);
      next();
    };
    next();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [pendingNow, projectId, enabled, apply]);

  // Ожидание после music_busy: раз в секунду — сколько осталось; вышло — «Создать» снова работает.
  const holdUntil = musicHold.until;
  useEffect(() => {
    if (!holdUntil) return;
    const timer = window.setInterval(() => {
      const left = cooldownLeft(holdUntil, Date.now());
      setMusicHold((h) => (h.until === holdUntil ? { until: left ? holdUntil : 0, left } : h));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [holdUntil]);

  // Ушли со страницы посреди загрузки трека — запрос не бросаем висеть.
  useEffect(
    () => () => {
      uploadAbort.current?.abort();
      settings.cancel();
    },
    [settings],
  );

  /* ---------- голоса ---------- */

  const loadVoices = useCallback(async () => {
    if (voicesLoading.current) return;
    voicesLoading.current = true;
    setVoices((v) => ({ ...v, loading: true, failed: false }));
    const res = await listVoices();
    voicesLoading.current = false;
    if (!res.ok || !Array.isArray(res.data)) {
      setVoices((v) => ({ ...v, loading: false, loaded: true, failed: true }));
      return;
    }
    const list = res.data;
    setVoices({ list, loading: false, loaded: true, failed: false });
    // Голос, которым озвучивали в прошлый раз, — сразу выбран.
    const remembered = readVoice();
    setDraft((d) => (d.voiceId && list.some((v) => v.id === d.voiceId) ? d : { ...d, voiceId: pickVoice(list, d.voiceId, remembered) }));
  }, []);

  /* ---------- отказы ---------- */

  /**
   * Отказ запроса звука. 402 — пополнение. Ответ не дошёл — сверяемся с сервером:
   * звук мог сделаться (тогда отказ снимаем), а повтор того же нажатия уйдёт с
   * тем же request_id. Остальное — текст у своего блока и свежее состояние.
   *
   * Метку заказа, ответ на который не дошёл, отказ не снимает (MA_V6 B1): отказ мог прийти
   * на другой запрос (свой трек, ✕), от защиты от частых запросов до того, как сервер
   * посмотрел на ключ, или на повтор, обогнавший сам заказ (music_busy), — а заказ мог
   * сделаться и списаться. Снимают её только звук склейки (его дорожка failed или ready —
   * settleRetry), ответ 2xx на него и сбой провайдера на сам этот заказ (orderFailedHere).
   * Id, которого сервер не видел, безвреден: следующее нажатие закажет под ним.
   * order — request_id, с которым ушёл этот заказ; upload — свой трек.
   */
  const fail = useCallback(
    async (kind: ErrorKind, id: string, err: VsError, before: string | null, opts: { upload?: boolean; order?: string } = {}) => {
      if (isAborted(err)) return;
      const upload = opts.upload === true;
      // Отказ — у своего блока открытой склейки; отказ той, с которой ушли, здесь не показываем.
      const show = (text: TextSpec | null) => {
        if (cb.current.projectId === id) setError(kind, text);
      };
      const lim = latest.current?.state.limits ?? DEFAULT_AUDIO_LIMITS;
      if (kind !== "settings" && opts.order && retry.current[kind]?.id === opts.order && orderFailedHere(err)) {
        retry.current[kind] = null;
      }
      const pw = paywallContext(err);
      if (pw) {
        show(null);
        cb.current.onPaywall(pw);
        void reload(id);
        return;
      }
      const transport = isTransportError(err);
      show(audioErrorText(err, lim, { upload }));
      if (kind === "music" && !upload) {
        const now = Date.now();
        const until = musicCooldownUntil(err, now, musicHoldUntil.current);
        if (until !== musicHoldUntil.current) {
          musicHoldUntil.current = until;
          setMusicHold({ until, left: cooldownLeft(until, now) });
        }
      }
      if (err.status === 400 || err.status === 429) return;
      const fresh = await reload(id);
      if (!fresh || kind === "settings") return;
      // Свой заказ узнаём по его request_id; у своего трека ключа нет — по смене готовой дорожки.
      const held = retry.current[kind];
      const own = !upload && held && held.project === id ? held.id : null;
      if (transport) {
        const outcome = afterLostAnswer(before, trackSlot(fresh.tracks, kind), own);
        if (outcome !== "lost") show(null);
        // Звук на самом деле сделан — как при ответе: форма закрыта, текст убран. Иначе
        // открытая форма «Заменить» с тем же текстом заказала бы тот же голос второй раз.
        if (outcome === "done" && cb.current.projectId === id) closeOrder(kind, upload);
      }
      // Вышел ли заказ, которого ждём, говорит не отказ, а звук склейки: его дорожка.
      settleRetry(kind, id, fresh, false);
    },
    [reload, setError, closeOrder, settleRetry],
  );

  /** Заказ идёт у другой склейки — кнопка здесь ждёт его: говорим, а не молчим. */
  const busyElsewhere = useCallback(
    (kind: "voice" | "music", owner: string | null, code = "audio_busy_other"): boolean => {
      if (owner === null) return false;
      if (owner !== (cb.current.projectId ?? NEW)) setError(kind, refusalText(code));
      return true;
    },
    [setError],
  );

  /* ---------- голос за кадром ---------- */

  const makeVoice = useCallback(async () => {
    if (busyElsewhere("voice", busy.current.voice)) return;
    const d = draftRef.current;
    const lim = latest.current?.state.limits ?? DEFAULT_AUDIO_LIMITS;
    const refusal = voiceRefusal(d.text, d.voiceId, lim);
    if (refusal) {
      setError("voice", refusal);
      return;
    }
    busy.current.voice = cb.current.projectId ?? NEW;
    setVoiceBusy(busy.current.voice);
    setError("voice", null);
    beginWork(work.current);
    try {
      const id = await cb.current.ensureSaved();
      if (!id) {
        setError("voice", refusalText("server_error"));
        return;
      }
      busy.current.voice = id;
      setVoiceBusy(id);
      const known = latest.current?.id === id ? latest.current.state : null;
      const before = known ? (trackSlot(known.tracks, "voice").ready?.id ?? null) : null;
      // Прежний заказ, ответ на который не дошёл, уже закончился (его дорожка не вышла или готова) —
      // это нажатие новый заказ. Иначе тот же слепок уйдёт с тем же request_id.
      if (retryVerdict(retry.current.voice, id, known?.tracks, "voice", false) !== "keep") retry.current.voice = null;
      const start = effectiveStart(d.start, cb.current.items.length);
      // Начало голоса в слепок не входит: фрагменты правили — заказ тот же (MA_V6 B2).
      const sig = voiceSignature(d.text, d.voiceId);
      const mark = retryMarkFor(retry.current.voice, id, sig);
      retry.current.voice = mark;
      const res = await makeVoiceApi(id, {
        text: cleanText(d.text),
        voice_id: d.voiceId,
        start_fragment: start,
        price: voicePrice(d.text, latest.current?.state.prices ?? DEFAULT_AUDIO_PRICES),
        request_id: mark.id,
      });
      if (res.ok) {
        retry.current.voice = null;
        apply(id, res.data);
        const answered = res.data.track;
        if (answered && replayedFailure(answered)) {
          // Сервер вернул прежнюю неудачную попытку того же нажатия: текст остаётся, следующее — новый заказ.
          if (cb.current.projectId === id) setError("voice", trackErrorText(answered));
          return;
        }
        rememberVoice(d.voiceId);
        if (cb.current.projectId === id) {
          setDraft((cur) => ({ ...cur, text: "" }));
          setForms((f) => ({ ...f, voice: false }));
          setLocal((l) => ({ ...l, start: undefined }));
        }
        // Повтор вернул голос с прежним началом, а фрагменты с тех пор правили — к его ролику.
        placeVoice(id, res.data, answered);
        setSaid(t("merge.audio.saidVoice", { defaultValue: "Голос за кадром готов" }));
        return;
      }
      await fail("voice", id, res.error, before, { order: mark.id });
    } finally {
      busy.current.voice = null;
      setVoiceBusy(null);
      endWork(work.current);
    }
  }, [apply, busyElsewhere, fail, placeVoice, setError, t]);

  /* ---------- музыка ---------- */

  const makeMusic = useCallback(async () => {
    if (busyElsewhere("music", busy.current.music)) return;
    // Места музыки только что были заняты — кнопка ждёт, причина видна под ней.
    if (cooldownLeft(musicHoldUntil.current, Date.now()) > 0) return;
    const d = draftRef.current;
    const cur = latest.current && latest.current.id === cb.current.projectId ? latest.current.state : null;
    const quote = musicQuote(cur, cb.current.items);
    const refusal = musicRefusal(d.prompt, quote?.seconds ?? 0, cur?.limits ?? DEFAULT_AUDIO_LIMITS);
    if (refusal) {
      setError("music", refusal);
      return;
    }
    busy.current.music = cb.current.projectId ?? NEW;
    setMusicBusy(busy.current.music);
    setError("music", null);
    beginWork(work.current);
    try {
      const id = await cb.current.ensureSaved();
      if (!id) {
        setError("music", refusalText("server_error"));
        return;
      }
      busy.current.music = id;
      setMusicBusy(id);
      const known = latest.current?.id === id ? latest.current.state : null;
      const before = known ? (trackSlot(known.tracks, "music").ready?.id ?? null) : null;
      // Прежний заказ, ответ на который не дошёл, уже закончился (его дорожка не вышла или готова) —
      // это нажатие новый заказ. Иначе тот же слепок уйдёт с тем же request_id.
      if (retryVerdict(retry.current.music, id, known?.tracks, "music", false) !== "keep") retry.current.music = null;
      const sig = musicSignature(d.prompt, quote?.seconds ?? 0);
      const mark = retryMarkFor(retry.current.music, id, sig);
      retry.current.music = mark;
      const res = await makeMusicApi(id, { prompt: cleanText(d.prompt), price: quote?.credits, request_id: mark.id });
      if (res.ok) {
        retry.current.music = null;
        apply(id, res.data);
        const answered = res.data.track;
        if (answered && replayedFailure(answered)) {
          // Сервер вернул прежнюю неудачную попытку того же нажатия: описание остаётся, следующее — новый заказ.
          if (cb.current.projectId === id) setError("music", trackErrorText(answered));
          return;
        }
        if (cb.current.projectId === id) {
          setDraft((x) => ({ ...x, prompt: "" }));
          setForms((f) => ({ ...f, music: false }));
        }
        setSaid(t("merge.audio.saidMusicQueued", { defaultValue: "Музыка создаётся — это около минуты" }));
        return;
      }
      await fail("music", id, res.error, before, { order: mark.id });
    } finally {
      busy.current.music = null;
      setMusicBusy(null);
      endWork(work.current);
    }
  }, [apply, busyElsewhere, fail, setError, t]);

  /** Свой трек вместо музыки: бесплатно, с прогрессом и отменой. */
  const uploadMusic = useCallback(
    async (file: File) => {
      if (busyElsewhere("music", uploadAbort.current ? uploadFor.current : null, "audio_upload_busy")) return;
      const lim = latest.current?.state.limits ?? DEFAULT_AUDIO_LIMITS;
      const pre = precheckAudio(file, lim);
      if (pre) {
        setError("music", audioErrorText({ code: pre, message: "", data: {} }, lim));
        return;
      }
      const ctrl = new AbortController();
      uploadAbort.current = ctrl;
      const key = cb.current.projectId ?? NEW;
      uploadFor.current = key;
      const name = file.name || t("merge.audio.ownTrack", { defaultValue: "Свой трек" });
      setUpload({ key, name, phase: "upload", pct: 0 });
      setError("music", null);
      beginWork(work.current);
      try {
        const id = await cb.current.ensureSaved();
        if (ctrl.signal.aborted) return;
        if (!id) {
          setError("music", refusalText("server_error"));
          return;
        }
        uploadFor.current = id;
        setUpload({ key: id, name, phase: "upload", pct: 0 });
        // Ответ не дошёл — «загружен» значит, что появился новый трек, а не что музыка вообще есть.
        const before = latest.current?.id === id ? trackSlot(latest.current.state.tracks, "music").ready?.id ?? null : null;
        const res = await uploadMusicApi(id, file, {
          filename: audioUploadName(file, lim) ?? undefined,
          signal: ctrl.signal,
          onProgress: (pct, phase) => {
            if (!ctrl.signal.aborted) setUpload({ key: id, name, phase, pct });
          },
        });
        if (res.ok) {
          apply(id, res.data);
          if (cb.current.projectId === id) setForms((f) => ({ ...f, music: false }));
          setSaid(t("merge.audio.saidUploaded", { defaultValue: "Свой трек загружен" }));
          return;
        }
        await fail("music", id, res.error, before, { upload: true });
      } finally {
        endWork(work.current);
        // Отменённую уже убрал cancelUpload — следующая могла начаться, её не трогаем.
        if (uploadAbort.current === ctrl) {
          uploadAbort.current = null;
          uploadFor.current = null;
          setUpload(null);
        }
      }
    },
    [apply, busyElsewhere, fail, setError, t],
  );

  /** Отмена — пока файл идёт; когда байты ушли, сервер его всё равно примет. */
  const cancelUpload = useCallback(() => {
    const ctrl = uploadAbort.current;
    if (!ctrl) return;
    uploadAbort.current = null;
    uploadFor.current = null;
    ctrl.abort();
    setUpload(null);
    setSaid(t("merge.upload.cancelled", { defaultValue: "Загрузка отменена" }));
  }, [t]);

  /* ---------- убрать дорожку ---------- */

  const removeTrack = useCallback(
    async (track: MergeTrack) => {
      const id = cb.current.projectId;
      if (!id) return;
      setDeleting(track.id);
      setError(track.kind, null);
      beginWork(work.current);
      try {
        const res = await deleteTrackApi(id, track.id);
        if (res.ok) {
          apply(id, res.data);
          if (track.status === "ready") {
            setSaid(
              track.kind === "voice"
                ? t("merge.audio.saidVoiceRemoved", { defaultValue: "Голос за кадром убран" })
                : t("merge.audio.saidMusicRemoved", { defaultValue: "Музыка убрана" }),
            );
          }
          return;
        }
        // Уже нет — значит, и показывать нечего.
        if (res.error.code === "audio_not_found") {
          void reload(id);
          return;
        }
        await fail(track.kind, id, res.error, null);
      } finally {
        setDeleting(null);
        endWork(work.current);
      }
    },
    [apply, fail, reload, setError, t],
  );

  /* ---------- звук роликов, громкость, начало голоса ---------- */

  /** Одна правка на сервер; true — принята. Очередь (settings) шлёт их по одной. */
  const sendSettings = useCallback(
    async (body: MergeAudioSettings): Promise<boolean> => {
      beginWork(work.current);
      try {
        const id = await cb.current.ensureSaved();
        if (!id) return false;
        const res = await patchAudio(id, body);
        const settle = (l: LocalSound) => settleLocal(l, body);
        if (res.ok) {
          apply(id, res.data);
          setLocal(settle);
          setError("settings", null);
          return true;
        }
        // Не приняли — на экране то, что на самом деле звучит.
        setLocal(settle);
        await fail("settings", id, res.error, null);
        return false;
      } finally {
        endWork(work.current);
      }
    },
    [apply, fail, setError],
  );

  useEffect(() => {
    sendRef.current = sendSettings;
  }, [sendSettings]);

  const setClipSound = useCallback(
    (clip: MergeClipSound) => {
      setLocal((l) => ({ ...l, clip }));
      settings.send({ clip_sound: clip });
    },
    [settings],
  );

  const setVolume = useCallback(
    (which: "music" | "voice", value: number) => {
      setLocal((l) => ({ ...l, [which]: value }));
      settings.later(
        which,
        () => {
          const v = localRef.current[which];
          if (v === undefined) return null;
          return which === "music" ? { music_volume: v } : { voice_volume: v };
        },
        VOLUME_DEBOUNCE_MS,
      );
    },
    [settings],
  );

  const moveVoice = useCallback(
    (start: number) => {
      setLocal((l) => ({ ...l, start }));
      settings.send({ voice_start_fragment: start });
    },
    [settings],
  );

  /**
   * Фрагменты переставили, убрали или добавили в начало: голос остаётся у своего
   * ролика (followStart) — и готовый (номер уходит на сервер, когда правки
   * улеглись), и тот, что в форме.
   */
  const followFragments = useCallback(
    (change: FragmentChange) => {
      const cur = cb.current;
      if (!isEditable(cur.status)) return;
      const count = cur.items.length;
      setDraft((d) => {
        const start = followStart(d.start, count, change);
        return start === d.start ? d : { ...d, start };
      });
      const s = latest.current && latest.current.id === cur.projectId ? latest.current.state : null;
      const slot = s ? trackSlot(s.tracks, "voice") : null;
      const track = slot ? slot.ready ?? slot.pending : null;
      if (!track) return;
      const from = effectiveStart(localRef.current.start ?? track.start_fragment ?? 0, count);
      const to = followStart(from, count, change);
      if (to === from) return;
      // Сразу и в ref: следующая правка списка (стрелки подряд) считает уже от нового номера.
      localRef.current = { ...localRef.current, start: to };
      setLocal((l) => ({ ...l, start: to }));
      settings.later(
        "start",
        () => {
          const v = localRef.current.start;
          return v === undefined ? null : { voice_start_fragment: v };
        },
        VOLUME_DEBOUNCE_MS,
      );
    },
    [settings],
  );

  /* ---------- формы ---------- */

  /** «Заменить»: форма с текстом, голосом и началом прежней дорожки — поправить и озвучить заново. */
  const openForm = useCallback((kind: MergeTrackKind, from: MergeTrack | null) => {
    setForms((f) => ({ ...f, [kind]: true }));
    if (!from) return;
    setDraft((d) =>
      kind === "voice"
        ? { ...d, text: d.text || from.text, voiceId: from.voice_id || d.voiceId, start: from.start_fragment ?? d.start }
        : { ...d, prompt: d.prompt || (from.source === "generated" ? from.prompt : "") },
    );
  }, []);

  const closeForm = useCallback(
    (kind: MergeTrackKind) => {
      setForms((f) => ({ ...f, [kind]: false }));
      setDraft((d) => (kind === "voice" ? { ...d, text: "" } : { ...d, prompt: "" }));
      setError(kind, null);
    },
    [setError],
  );

  /* ---------- что на экране ---------- */

  const voice = trackSlot(state?.tracks, "voice");
  const music = trackSlot(state?.tracks, "music");
  const clip: MergeClipSound = local.clip ?? state?.clip_sound ?? summary?.clip_sound ?? "keep";
  const info = soundInfo(state ? { tracks: state.tracks, clip_sound: clip } : null, summary ? { ...summary, clip_sound: clip } : null);
  const current = projectId ?? NEW;
  const voiceBusyNow = voiceBusy !== null && (voiceBusy === current || voiceBusy === NEW);
  const musicBusyNow = musicBusy !== null && (musicBusy === current || musicBusy === NEW);
  const uploadNow = upload && (upload.key === current || upload.key === NEW) ? upload : null;
  const quote = musicQuote(state, items);
  const savedStart = voice.ready?.start_fragment ?? 0;

  return {
    /** Склейка заведена — звук есть куда сохранить. */
    available: projectId !== null,
    state,
    loading: Boolean(projectId) && !state && loadFailed !== projectId,
    loadFailed: Boolean(projectId) && !state && loadFailed === projectId,
    editable: editableStatus && (state?.editable ?? true),
    configured: state ? state.configured : true,
    limits,
    prices,
    voices,
    draft,
    forms,
    errors,
    voice,
    music,
    clip,
    musicVolume: local.music ?? state?.music_volume ?? summary?.music_volume ?? DEFAULT_MUSIC_VOLUME,
    voiceVolume: local.voice ?? state?.voice_volume ?? summary?.voice_volume ?? DEFAULT_VOICE_VOLUME,
    /** С какого фрагмента звучит готовый голос — с поправкой на убранные фрагменты. */
    voiceStart: effectiveStart(local.start ?? savedStart, items.length),
    voicePrice: voicePrice(draft.text, prices),
    musicQuote: quote,
    info,
    paid: paidSound(info),
    voiceBusy: voiceBusyNow,
    musicBusy: musicBusyNow,
    /** Секунд до нового заказа музыки после music_busy; 0 — можно. */
    musicWait: musicHold.left,
    upload: uploadNow,
    deleting,
    /** «Склеить» подождёт: звук делается или свой трек ещё идёт. */
    blocking: info.pending || voiceBusyNow || musicBusyNow || uploadNow !== null,
    /**
     * Перед запуском склейки: отложенная правка звука уходит сразу, и все правки
     * доходят до сервера раньше запуска. false — какую-то не приняли.
     */
    flushSettings: settings.flush,
    said,
    actions: {
      reload: () => {
        setLoadFailed(null);
        setReloadKey((k) => k + 1);
      },
      /** Стабильная ссылка: панель зовёт её из эффекта, когда форма голоса на экране. */
      loadVoices,
      setText: (text: string) => setDraft((d) => ({ ...d, text })),
      setVoiceId: (voiceId: string) => setDraft((d) => ({ ...d, voiceId })),
      setStart: (start: number) => setDraft((d) => ({ ...d, start })),
      setPrompt: (prompt: string) => setDraft((d) => ({ ...d, prompt })),
      makeVoice: () => void makeVoice(),
      makeMusic: () => void makeMusic(),
      uploadMusic: (file: File) => void uploadMusic(file),
      cancelUpload,
      /** Promise — чтобы панель вернула фокус, когда дорожка исчезнет. */
      removeTrack,
      setClipSound,
      setMusicVolume: (v: number) => setVolume("music", v),
      setVoiceVolume: (v: number) => setVolume("voice", v),
      moveVoice,
      followFragments,
      openForm,
      closeForm,
      dismissError: (kind: ErrorKind) => setError(kind, null),
    },
  };
}
