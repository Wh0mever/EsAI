"use client";

import { useTranslation } from "react-i18next";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  FiLoader,
  FiMic,
  FiMusic,
  FiPause,
  FiPlay,
  FiSquare,
  FiTrash2,
  FiUpload,
  FiVolume2,
  FiZap,
} from "react-icons/fi";
import { Modal } from "@/components/dialog/Dialog";
import {
  VS_BTN_GHOST,
  VS_BTN_GOLD,
  VS_FOCUS,
  VS_INPUT,
  VS_LABEL,
  VS_PILL,
  VS_PILL_ON,
  vx,
} from "@/components/vstudio/ui/skin";
import { fetchData } from "@/tools/fetchData";
import type { StudioScene } from "./SceneTimeline";
import type { ApiRefusal } from "./cartoonTypes";
import { clipSeconds } from "./dockLogic";
import { CS_NOTE_GOLD } from "./ui/cartoonSkin";

/**
 * Звук сцены: реплики героев, свой голос, музыка и эффекты.
 *
 * Клиент: «максимально просто». Поэтому одна вкладка — одно действие, цена
 * видна на самой кнопке ещё до генерации, а у каждой готовой дорожки всего два
 * ползунка: когда начинается и насколько громко. Сведение со сценой делается
 * само — при закрытии окна, если что-то поменялось, а у ещё не снятой сцены —
 * сразу после съёмки.
 */

export type AudioConfig = {
  enabled: boolean;
  prices: { voice_per_1k: number; voice_min: number; music_per_min: number; sfx: number };
  limits: { voice_chars: number; music_sec: [number, number]; sfx_sec: [number, number]; upload_mb: number };
};

type Voice = {
  id: string;
  name: string;
  gender: string;
  age: string;
  accent: string;
  description: string;
  use_case: string;
  preview: string;
};

type Track = {
  id: number;
  /** Музыка и эффекты делаются в фоне: сперва «готовится», потом «готова». */
  status?: "pending" | "ready" | "failed";
  error?: string;
  credits_planned?: number;
  kind: "voice" | "own" | "music" | "sfx";
  text: string;
  voice_id: string;
  voice_name: string;
  character: { id: number; name: string } | null;
  file: string;
  duration: number;
  start_sec: number;
  volume: number;
  credits_spent: number;
};

type SceneAudio = {
  scene_id: number;
  sound_volume: number;
  has_video: boolean;
  mixed_video: string;
  tracks: Track[];
};

type Tab = "voice" | "own" | "music" | "sfx";

const TAB_ICON = { voice: FiZap, own: FiMic, music: FiMusic, sfx: FiVolume2 };

const LAST_VOICE_KEY = "esai.studio.voiceByCharacter";

/** Перевод подписи голоса: незнакомое слово возвращается как есть (defaultValue). */
type Tr = (key: string, options: { defaultValue: string }) => string;

/** Числовое поле окна: 44 px на телефоне, шрифт 16 px — иначе iOS приближает страницу. */
const NUMBER_FIELD = vx(VS_INPUT, "!min-h-11 !w-20 !px-2 tabular-nums max-sm:!text-base md:!min-h-9");
/** Поле текста окна (реплика, описание музыки или эффекта). */
const TEXT_FIELD = vx(VS_INPUT, "resize-none py-2 leading-snug max-sm:!text-base");
/** Ползунок дорожки: высокая зона нажатия на телефоне. */
const RANGE = "h-11 min-w-0 flex-1 cursor-pointer accent-[var(--accent)] md:h-8";
const SPIN = "animate-spin motion-reduce:animate-none";

/**
 * Подпись голоса на языке человека.
 *
 * ElevenLabs размечает голоса по-английски («female · middle_aged ·
 * professional»), и в русском интерфейсе это выглядит как служебный вывод.
 * Переводим то, что знаем, а незнакомое слово показываем как есть.
 */
/** «Bella - Professional, Bright, Warm» → «Bella». */
function voiceShortName(v: Voice): string {
  return (v.name || "").split(" - ")[0].trim() || v.name;
}

/** Характер голоса по-русски: «мягкий, тёплый». Для известных голосов —
 *  написанное руками описание, для остальных — перевод слов из названия. */
function voiceCharacter(v: Voice, t: Tr): string {
  const key = voiceShortName(v).toLowerCase().replace(/[^a-z]+/g, "");
  const known = t(`studio_ui.voice_n_${key}`, { defaultValue: "" });
  if (known) return known;
  const tail = (v.name || "").split(" - ")[1] || v.description || "";
  return tail
    .split(/,| and /)
    .map((w) => w.trim())
    .filter(Boolean)
    .map((w) =>
      t(`studio_ui.voice_w_${w.toLowerCase().replace(/[^a-z]+/g, "_")}`, { defaultValue: w })
    )
    .join(", ");
}

function voiceTraits(v: Voice, t: Tr): string {
  const word = (raw: string) =>
    raw ? t(`studio_ui.voice_w_${raw.toLowerCase().replace(/[^a-z_]+/g, "_")}`, { defaultValue: raw }) : "";
  return [word(v.gender), word(v.age)].filter(Boolean).join(" · ");
}

function readVoiceMemory(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(LAST_VOICE_KEY) || "{}") || {};
  } catch {
    return {};
  }
}

function rememberVoice(characterId: number | null, voiceId: string) {
  if (!characterId) return;
  try {
    const all = readVoiceMemory();
    all[String(characterId)] = voiceId;
    localStorage.setItem(LAST_VOICE_KEY, JSON.stringify(all));
  } catch {
    /* память голоса — удобство, без неё всё работает */
  }
}

export default function SceneAudioDialog({
  scene,
  config,
  characters,
  onClose,
  onChanged,
  onNeedCredits,
}: {
  scene: StudioScene | null;
  config: AudioConfig | null;
  /** Чьи реплики можно озвучить: герои ленты. */
  characters: { id: number; name: string }[];
  onClose: () => void;
  /** Звук сцены поменялся и уже сведён (или сведётся после съёмки). */
  onChanged: () => void;
  onNeedCredits: (required: number, balance: number) => void;
}) {
  const { t, i18n } = useTranslation("common");
  const open = Boolean(scene);
  const [data, setData] = useState<SceneAudio | null>(null);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [tab, setTab] = useState<Tab>("voice");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);

  const [text, setText] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [characterId, setCharacterId] = useState<number | null>(null);
  const [prompt, setPrompt] = useState("");
  const [seconds, setSeconds] = useState(10);
  const [startSec, setStartSec] = useState(0);

  const [recording, setRecording] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const previewRef = useRef<HTMLAudioElement | null>(null);
  const [previewing, setPreviewing] = useState<string | null>(null);

  // Длина настоящего ролика: у снятой сцены — по съёмке, а не по нынешнему доку
  // (preset.duration — это уже длительность следующей съёмки).
  const sceneDuration = clipSeconds(scene);
  const prices = config?.prices;

  useEffect(() => {
    if (!scene) return;
    setData(null);
    setError("");
    setDirty(false);
    setText("");
    setPrompt("");
    setStartSec(0);
    setTab("voice");
    setSeconds(Math.max(config?.limits.music_sec[0] ?? 3, Math.min(30, sceneDuration)));
    const heroId = scene.character?.id ?? null;
    setCharacterId(heroId);
    const remembered = heroId ? readVoiceMemory()[String(heroId)] : "";
    if (remembered) setVoiceId(remembered);
    void (async () => {
      const res = await fetchData<SceneAudio>(`cartoon/scenes/${scene.id}/audio/`, "GET", undefined, true);
      if (res.ok && res.data) {
        setData(res.data);
        return;
      }
      // Не загрузилось — показываем пустой список, а не вечный спиннер:
      // иначе окно выглядит сломанным, а сделанный звук «пропадает».
      setData({
        scene_id: scene.id,
        sound_volume: 1,
        has_video: Boolean(scene.video),
        mixed_video: "",
        tracks: [],
      });
      setError(t("studio_ui.audio_err_load"));
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene?.id]);

  useEffect(() => {
    if (!open || voices.length) return;
    void (async () => {
      const res = await fetchData<Voice[]>("cartoon/audio/voices/", "GET", undefined, false);
      if (res.ok && Array.isArray(res.data)) {
        const list = res.data;
        setVoices(list);
        setVoiceId((v) => v || list[0]?.id || "");
      }
    })();
  }, [open, voices.length]);

  // Голос героя запоминается: второй раз озвучивая того же героя, человек
  // не ищет голос заново, и герой звучит одинаково во всех сценах.
  useEffect(() => {
    if (!characterId) return;
    const remembered = readVoiceMemory()[String(characterId)];
    if (remembered) setVoiceId(remembered);
  }, [characterId]);

  // Музыка и эффекты делаются в фоне. Пока хоть одна дорожка «готовится»,
  // перечитываем список — человек видит, как она становится готовой.
  const pendingCount = (data?.tracks || []).filter((x) => x.status === "pending").length;
  useEffect(() => {
    if (!scene || pendingCount === 0) return;
    const sceneId = scene.id;
    const timer = window.setInterval(async () => {
      const res = await fetchData<SceneAudio>(`cartoon/scenes/${sceneId}/audio/`, "GET", undefined, true);
      if (!res.ok || !res.data) return;
      const fresh = res.data;
      setData((prev) => {
        if (!prev) return fresh;
        // Дорожка доделалась — баланс изменился, а сцена могла получить звук.
        const wasPending = prev.tracks.filter((x) => x.status === "pending").length;
        const nowPending = fresh.tracks.filter((x) => x.status === "pending").length;
        if (nowPending < wasPending) setDirty(true);
        return fresh;
      });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [scene, pendingCount]);

  const voicePrice = useMemo(() => {
    if (!prices) return 0;
    return Math.max(prices.voice_min, Math.ceil((text.trim().length * prices.voice_per_1k) / 1000));
  }, [text, prices]);
  const musicPrice = prices ? Math.max(1, Math.ceil((seconds * prices.music_per_min) / 60)) : 0;
  const sfxPrice = prices?.sfx ?? 0;

  // Окно закрыли посреди записи или прослушивания — освобождаем микрофон и звук.
  useEffect(
    () => () => {
      try {
        recorderRef.current?.stop();
      } catch {
        /* записи уже нет */
      }
      streamRef.current?.getTracks().forEach((tr) => tr.stop());
      streamRef.current = null;
      previewRef.current?.pause();
    },
    []
  );

  const stopPreview = () => {
    previewRef.current?.pause();
    setPreviewing(null);
  };

  /** Пример голоса. Клиент: он должен звучать по-русски — родной образец у
   *  провайдера английский, и по нему не понять, как заговорит герой. */
  const playPreview = async (v: Voice) => {
    if (previewing === v.id) {
      stopPreview();
      return;
    }
    previewRef.current?.pause();
    setPreviewing(v.id);
    const lang = (i18n.language || "ru").slice(0, 2);
    const res = await fetchData<{ url: string }>(
      `cartoon/audio/voices/${encodeURIComponent(v.id)}/preview/?lang=${lang === "ky" ? "kg" : lang}`,
      "GET", undefined, false
    );
    const src = (res.ok && res.data?.url) || v.preview;
    if (!src) {
      setPreviewing(null);
      return;
    }
    const a = new Audio(src);
    previewRef.current = a;
    a.onended = () => setPreviewing(null);
    void a.play().catch(() => setPreviewing(null));
  };

  const addTrack = (track: Track) => {
    setData((d) => {
      const base: SceneAudio = d || {
        scene_id: scene?.id ?? 0,
        sound_volume: 1,
        has_video: Boolean(scene?.video),
        mixed_video: "",
        tracks: [],
      };
      return { ...base, tracks: [...base.tracks, track].sort((a, b) => a.start_sec - b.start_sec) };
    });
    setDirty(true);
  };

  const handleError = (res: { data: unknown; error?: string }) => {
    const d = res.data as ApiRefusal;
    if (d?.required) {
      onNeedCredits(Number(d.required), Number(d.balance ?? 0));
    } else {
      setError(d?.detail || res.error || t("studio_ui.audio_err"));
    }
  };

  const generate = async (kind: "voice" | "music" | "sfx") => {
    if (!scene) return;
    setError("");
    let body: Record<string, unknown>;
    if (kind === "voice") {
      if (!text.trim()) return setError(t("studio_ui.audio_err_text"));
      if (!voiceId) return setError(t("studio_ui.audio_err_voice"));
      body = { text: text.trim(), voice_id: voiceId, character_id: characterId, start_sec: startSec };
    } else if (kind === "music") {
      if (prompt.trim().length < 3) return setError(t("studio_ui.audio_err_prompt"));
      body = { prompt: prompt.trim(), seconds, start_sec: startSec, volume: 0.5 };
    } else {
      if (prompt.trim().length < 3) return setError(t("studio_ui.audio_err_prompt"));
      body = { prompt: prompt.trim(), start_sec: startSec };
    }
    setBusy(kind);
    const res = await fetchData<Track>(`cartoon/scenes/${scene.id}/audio/${kind}/`, "POST", body, true);
    setBusy(null);
    if (res.ok && res.data) {
      addTrack(res.data);
      if (kind === "voice") {
        rememberVoice(characterId, voiceId);
        setText("");
      } else {
        setPrompt("");
      }
    } else {
      handleError(res);
    }
  };

  const uploadBlob = async (blob: Blob, name: string) => {
    if (!scene) return;
    if (config && blob.size > config.limits.upload_mb * 1024 * 1024) {
      setError(t("studio_ui.audio_err_big", { mb: config.limits.upload_mb }));
      return;
    }
    const fd = new FormData();
    fd.append("file", blob, name);
    fd.append("start_sec", String(startSec));
    if (characterId) fd.append("character_id", String(characterId));
    setBusy("own");
    setError("");
    const res = await fetchData<Track>(`cartoon/scenes/${scene.id}/audio/upload/`, "POST", fd, true);
    setBusy(null);
    if (res.ok && res.data) addTrack(res.data);
    else handleError(res);
  };

  const startRecording = async () => {
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const rec = new MediaRecorder(stream);
      chunksRef.current = [];
      rec.ondataavailable = (e) => e.data.size && chunksRef.current.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((tr) => tr.stop());
        streamRef.current = null;
        const type = rec.mimeType || "audio/webm";
        const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
        void uploadBlob(new Blob(chunksRef.current, { type }), `voice.${ext}`);
      };
      recorderRef.current = rec;
      rec.start();
      setRecording(true);
    } catch {
      streamRef.current?.getTracks().forEach((tr) => tr.stop());
      streamRef.current = null;
      setError(t("studio_ui.audio_err_mic"));
    }
  };

  const stopRecording = () => {
    recorderRef.current?.stop();
    recorderRef.current = null;
    setRecording(false);
  };

  const patchTrack = async (track: Track, patch: Partial<Pick<Track, "start_sec" | "volume">>) => {
    const prev = data;
    setData((d) => (d ? { ...d, tracks: d.tracks.map((x) => (x.id === track.id ? { ...x, ...patch } : x)) } : d));
    setDirty(true);
    const res = await fetchData(`cartoon/audio/${track.id}/`, "PATCH", patch, true);
    // Сервер не принял правку — возвращаем то, что есть на самом деле:
    // иначе ползунок показывал бы одно, а в ролике звучало другое.
    if (!res.ok) {
      setData(prev);
      setError((res.data as ApiRefusal)?.detail || t("studio_ui.audio_err"));
    }
  };

  const removeTrack = async (track: Track) => {
    const prev = data;
    setData((d) => (d ? { ...d, tracks: d.tracks.filter((x) => x.id !== track.id) } : d));
    setDirty(true);
    const res = await fetchData(`cartoon/audio/${track.id}/`, "DELETE", undefined, true);
    if (!res.ok) {
      setData(prev);
      setError((res.data as ApiRefusal)?.detail || t("studio_ui.audio_err"));
    }
  };

  const setSceneVolume = async (value: number) => {
    if (!scene) return;
    const prev = data;
    setData((d) => (d ? { ...d, sound_volume: value } : d));
    setDirty(true);
    const res = await fetchData(`cartoon/scenes/${scene.id}/audio/`, "PATCH",
                                { sound_volume: value }, true);
    if (!res.ok) setData(prev);
  };

  /** Свести звук со сценой и закрыть. У не снятой сцены сведение будет после съёмки. */
  const finish = async () => {
    if (recording) stopRecording();
    stopPreview();
    if (scene && dirty && data?.has_video) {
      setBusy("mix");
      const res = await fetchData(`cartoon/scenes/${scene.id}/audio/mix/`, "POST", {}, true);
      setBusy(null);
      if (!res.ok) {
        setError((res.data as ApiRefusal)?.detail || t("studio_ui.audio_err_mix"));
        return;
      }
    }
    if (dirty) onChanged();
    onClose();
  };

  const tabs: { key: Tab; label: string }[] = [
    { key: "voice", label: t("studio_ui.audio_tab_voice") },
    { key: "own", label: t("studio_ui.audio_tab_own") },
    { key: "music", label: t("studio_ui.audio_tab_music") },
    { key: "sfx", label: t("studio_ui.audio_tab_sfx") },
  ];

  const startField = (
    <label className="flex items-center gap-2 text-xs text-muted">
      {t("studio_ui.audio_start")}
      <input
        type="number"
        min={0}
        max={sceneDuration}
        step={0.5}
        value={startSec}
        onChange={(e) => setStartSec(Math.max(0, Number(e.target.value) || 0))}
        className={NUMBER_FIELD}
      />
      {t("studio_ui.audio_sec")}
    </label>
  );

  const actionBtn = (label: string, onClick: () => void, key: string, disabled = false) => (
    <button
      type="button"
      onClick={onClick}
      disabled={busy !== null || disabled}
      aria-busy={busy === key || undefined}
      // Платное действие вкладки — золотое: цена на самой кнопке.
      className={VS_BTN_GOLD}
    >
      {busy === key ? <FiLoader className={SPIN} aria-hidden /> : <FiZap aria-hidden />}
      {busy === key ? t("studio_ui.audio_making") : label}
    </button>
  );

  return (
    <Modal open={open} onClose={() => void finish()} title={t("studio_ui.audio_title")} size="lg">
      {!config?.enabled ? (
        <p className="text-sm text-muted">{t("studio_ui.audio_off")}</p>
      ) : (
        <div className="flex flex-col gap-4">
          <p className="text-xs text-muted-2">
            {scene?.custom_text || scene?.preset.title} · {sceneDuration} {t("studio_ui.audio_sec")}
            {data && !data.has_video ? ` · ${t("studio_ui.audio_after_render")}` : ""}
          </p>

          <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4" role="group" aria-label={t("studio_ui.audio_title")}>
            {tabs.map((tb) => {
              const Icon = TAB_ICON[tb.key];
              return (
                <button
                  key={tb.key}
                  type="button"
                  onClick={() => {
                    setTab(tb.key);
                    setError("");
                  }}
                  aria-pressed={tab === tb.key}
                  className={vx(VS_PILL, "!h-11 justify-center !px-2 !text-xs !font-semibold md:!h-10", tab === tb.key && VS_PILL_ON)}
                >
                  <Icon aria-hidden /> {tb.label}
                </button>
              );
            })}
          </div>

          {(tab === "voice" || tab === "own") && characters.length > 0 && (
            <label className="flex flex-col gap-1 text-xs text-muted">
              {t("studio_ui.audio_who")}
              <select
                value={characterId ?? ""}
                onChange={(e) => setCharacterId(e.target.value ? Number(e.target.value) : null)}
                className={vx(VS_INPUT, "cursor-pointer max-sm:!text-base")}
              >
                <option value="">{t("studio_ui.audio_narrator")}</option>
                {characters.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          {tab === "voice" && (
            <div className="flex flex-col gap-3">
              <p className={vx(CS_NOTE_GOLD, "!rounded-xl !px-3 !py-2 !text-[12px] leading-snug")}>
                {t("studio_ui.audio_lips_note")}
              </p>
              <div className="flex flex-col gap-1">
                <span className="text-sm font-semibold text-foreground">
                  {t("studio_ui.audio_voice")}
                </span>
                <span className="text-[11px] text-muted-2">{t("studio_ui.audio_voice_note")}</span>
                <div className="grid max-h-44 grid-cols-1 gap-1.5 overflow-y-auto pr-1 sm:grid-cols-2">
                  {voices.length === 0 && <span className="text-xs text-muted-2">{t("studio_ui.audio_loading")}</span>}
                  {voices.map((v) => (
                    <div
                      key={v.id}
                      className={vx(
                        "flex items-center gap-2 rounded-xl border px-1.5 py-1 transition-colors",
                        voiceId === v.id ? "border-vs-accent/45 bg-accent/[0.1]" : "border-vs-ink/10 hover:border-vs-ink/20",
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => void playPreview(v)}
                        aria-label={`${t("studio_ui.audio_listen")}: ${voiceShortName(v)}`}
                        aria-pressed={previewing === v.id}
                        title={t("studio_ui.audio_listen")}
                        className={vx(
                          "grid size-11 shrink-0 cursor-pointer place-items-center rounded-full bg-vs-ink/[0.06] text-foreground transition-colors hover:bg-vs-ink/[0.1] disabled:opacity-40 md:size-8",
                          VS_FOCUS,
                        )}
                      >
                        {previewing === v.id ? <FiPause aria-hidden /> : <FiPlay aria-hidden />}
                      </button>
                      <button
                        type="button"
                        onClick={() => setVoiceId(v.id)}
                        aria-pressed={voiceId === v.id}
                        className={vx("min-h-11 min-w-0 flex-1 cursor-pointer rounded-lg px-1 text-left md:min-h-9", VS_FOCUS)}
                      >
                        <div className="truncate text-sm text-foreground">
                          <span className="font-semibold">{voiceShortName(v)}</span>
                          <span className="text-muted"> — {voiceCharacter(v, t)}</span>
                        </div>
                        <div className="truncate text-[10px] text-muted-2">
                          {voiceTraits(v, t)}
                        </div>
                      </button>
                    </div>
                  ))}
                </div>
              </div>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value.slice(0, config.limits.voice_chars))}
                rows={3}
                placeholder={t("studio_ui.audio_text_ph")}
                className={TEXT_FIELD}
              />
              <div className="flex flex-wrap items-center justify-between gap-3">
                {startField}
                <span className="text-[11px] tabular-nums text-muted-2">
                  {text.trim().length}/{config.limits.voice_chars}
                </span>
              </div>
              {actionBtn(t("studio_ui.audio_voice_btn", { credits: voicePrice }), () => void generate("voice"), "voice")}
            </div>
          )}

          {tab === "own" && (
            <div className="flex flex-col gap-3">
              <p className="text-xs text-muted-2">{t("studio_ui.audio_own_note")}</p>
              {startField}
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={recording ? stopRecording : () => void startRecording()}
                  disabled={busy !== null}
                  aria-pressed={recording}
                  aria-busy={busy === "own" || undefined}
                  // Идёт запись — красный контур: так кнопку «Остановить» видно в обеих темах.
                  className={
                    recording
                      ? vx(VS_BTN_GHOST, "!border-status-fail/50 !bg-status-fail/10 !font-semibold !text-status-fail")
                      : VS_BTN_GOLD
                  }
                >
                  {busy === "own" ? (
                    <FiLoader className={SPIN} aria-hidden />
                  ) : recording ? (
                    <FiSquare aria-hidden />
                  ) : (
                    <FiMic aria-hidden />
                  )}
                  {recording ? t("studio_ui.audio_rec_stop") : t("studio_ui.audio_rec")}
                </button>
                <button
                  type="button"
                  onClick={() => fileRef.current?.click()}
                  disabled={busy !== null || recording}
                  className={VS_BTN_GHOST}
                >
                  <FiUpload aria-hidden /> {t("studio_ui.audio_upload")}
                </button>
                <input
                  ref={fileRef}
                  type="file"
                  accept="audio/*"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void uploadBlob(f, f.name);
                    e.target.value = "";
                  }}
                />
              </div>
              <p className="text-[11px] text-muted-2">{t("studio_ui.audio_own_free")}</p>
            </div>
          )}

          {(tab === "music" || tab === "sfx") && (
            <div className="flex flex-col gap-3">
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={2}
                placeholder={t(tab === "music" ? "studio_ui.audio_music_ph" : "studio_ui.audio_sfx_ph")}
                className={TEXT_FIELD}
              />
              <div className="flex flex-wrap items-center gap-4">
                {startField}
                {tab === "music" && (
                  <label className="flex items-center gap-2 text-xs text-muted">
                    {t("studio_ui.audio_length")}
                    <input
                      type="number"
                      min={config.limits.music_sec[0]}
                      max={config.limits.music_sec[1]}
                      value={seconds}
                      onChange={(e) =>
                        setSeconds(
                          Math.min(config.limits.music_sec[1], Math.max(config.limits.music_sec[0], Number(e.target.value) || 0))
                        )
                      }
                      className={NUMBER_FIELD}
                    />
                    {t("studio_ui.audio_sec")}
                  </label>
                )}
              </div>
              {tab === "music"
                ? actionBtn(t("studio_ui.audio_music_btn", { credits: musicPrice }), () => void generate("music"), "music")
                : actionBtn(t("studio_ui.audio_sfx_btn", { credits: sfxPrice }), () => void generate("sfx"), "sfx")}
            </div>
          )}

          {error && (
            <p role="alert" className="text-sm leading-snug text-status-fail">
              {error}
            </p>
          )}

          {/* Готовые дорожки: когда начинается и насколько громко. */}
          <div className="flex flex-col gap-2 border-t border-vs-ink/10 pt-3">
            <div className={VS_LABEL}>{t("studio_ui.audio_tracks")}</div>
            {data && data.has_video && (
              <label className="flex items-center gap-3 text-xs text-muted">
                <span className="w-28 shrink-0">{t("studio_ui.audio_scene_sound")}</span>
                <input
                  type="range"
                  min={0}
                  max={2}
                  step={0.05}
                  value={data.sound_volume}
                  onChange={(e) => setData({ ...data, sound_volume: Number(e.target.value) })}
                  onMouseUp={(e) => void setSceneVolume(Number((e.target as HTMLInputElement).value))}
                  onTouchEnd={(e) => void setSceneVolume(Number((e.target as HTMLInputElement).value))}
                  onKeyUp={(e) => void setSceneVolume(Number((e.target as HTMLInputElement).value))}
                  className={RANGE}
                />
                <span className="w-10 text-right tabular-nums">{Math.round(data.sound_volume * 100)}%</span>
              </label>
            )}
            {!data && <FiLoader className={vx(SPIN, "text-muted")} aria-hidden />}
            {data?.tracks.length === 0 && <p className="text-xs text-muted-2">{t("studio_ui.audio_no_tracks")}</p>}
            {data?.tracks.map((tr) => {
              const Icon = TAB_ICON[tr.kind === "voice" ? "voice" : tr.kind];
              const overflow = tr.start_sec + tr.duration > sceneDuration + 0.05;
              return (
                <div key={tr.id} className="flex flex-col gap-2 rounded-xl border border-vs-ink/10 bg-vs-ink/[0.03] p-2.5">
                  <div className="flex items-start gap-2">
                    <Icon className="mt-0.5 shrink-0 text-vs-accent" aria-hidden />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm text-foreground">
                        {tr.character ? `${tr.character.name}: ` : ""}
                        {tr.text || t(`studio_ui.audio_tab_${tr.kind}`)}
                      </div>
                      <div className="text-[11px] tabular-nums text-muted-2">
                        {[tr.voice_name, `${tr.duration.toFixed(1)} ${t("studio_ui.audio_sec")}`,
                          tr.credits_spent ? `${tr.credits_spent} ${t("studio_ui.credits_short")}` : ""]
                          .filter(Boolean)
                          .join(" · ")}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => void removeTrack(tr)}
                      aria-label={t("studio_ui.remove")}
                      title={t("studio_ui.remove")}
                      className={vx(
                        "-my-1.5 grid size-11 shrink-0 cursor-pointer place-items-center rounded-full text-muted transition-colors hover:bg-vs-ink/[0.08] hover:text-status-fail md:my-0 md:size-8",
                        VS_FOCUS,
                      )}
                    >
                      <FiTrash2 aria-hidden />
                    </button>
                  </div>
                  {tr.status === "pending" && (
                    <p className="flex items-center gap-2 text-xs text-muted">
                      <FiLoader className={SPIN} aria-hidden /> {t("studio_ui.audio_pending")}
                    </p>
                  )}
                  {tr.status === "failed" && (
                    <p className="text-xs leading-snug text-status-fail">{tr.error || t("studio_ui.audio_failed")}</p>
                  )}
                  {(!tr.status || tr.status === "ready") && (
                  <audio src={tr.file} controls preload="none" className="h-8 w-full" />
                  )}
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    <label className="flex items-center gap-2 text-[11px] text-muted">
                      <span className="w-14 shrink-0">{t("studio_ui.audio_start_short")}</span>
                      <input
                        type="range"
                        min={0}
                        max={sceneDuration}
                        step={0.1}
                        value={tr.start_sec}
                        onChange={(e) => {
                          const v = Number(e.target.value);
                          setData((d) => d && { ...d, tracks: d.tracks.map((x) => (x.id === tr.id ? { ...x, start_sec: v } : x)) });
                        }}
                        onMouseUp={(e) => void patchTrack(tr, { start_sec: Number((e.target as HTMLInputElement).value) })}
                        onTouchEnd={(e) => void patchTrack(tr, { start_sec: Number((e.target as HTMLInputElement).value) })}
                        onKeyUp={(e) => void patchTrack(tr, { start_sec: Number((e.target as HTMLInputElement).value) })}
                        className={RANGE}
                      />
                      <span className="w-10 text-right tabular-nums">{tr.start_sec.toFixed(1)}</span>
                    </label>
                    <label className="flex items-center gap-2 text-[11px] text-muted">
                      <span className="w-14 shrink-0">{t("studio_ui.audio_volume")}</span>
                      <input
                        type="range"
                        min={0}
                        max={2}
                        step={0.05}
                        value={tr.volume}
                        onChange={(e) => {
                          const v = Number(e.target.value);
                          setData((d) => d && { ...d, tracks: d.tracks.map((x) => (x.id === tr.id ? { ...x, volume: v } : x)) });
                        }}
                        onMouseUp={(e) => void patchTrack(tr, { volume: Number((e.target as HTMLInputElement).value) })}
                        onTouchEnd={(e) => void patchTrack(tr, { volume: Number((e.target as HTMLInputElement).value) })}
                        onKeyUp={(e) => void patchTrack(tr, { volume: Number((e.target as HTMLInputElement).value) })}
                        className={RANGE}
                      />
                      <span className="w-10 text-right tabular-nums">{Math.round(tr.volume * 100)}%</span>
                    </label>
                  </div>
                  {overflow && <p className="text-[11px] leading-snug text-status-wait">{t("studio_ui.audio_overflow")}</p>}
                </div>
              );
            })}
          </div>

          <button
            type="button"
            onClick={() => void finish()}
            disabled={busy === "mix" || recording}
            aria-busy={busy === "mix" || undefined}
            className={vx(VS_BTN_GHOST, "!border-vs-accent/45 !font-semibold !text-vs-accent hover:!bg-accent/[0.1]")}
          >
            {busy === "mix" ? <FiLoader className={SPIN} aria-hidden /> : null}
            {busy === "mix"
              ? t("studio_ui.audio_mixing")
              : dirty && data?.has_video
              ? t("studio_ui.audio_apply")
              : t("studio_ui.audio_done")}
          </button>
        </div>
      )}
    </Modal>
  );
}
