"use client";

import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useRef, useState } from "react";
import { FiPause, FiPlay } from "react-icons/fi";
import { VS_FOCUS, vx } from "@/components/vstudio/ui/skin";
import { fetchData } from "@/tools/fetchData";
import { shortVoiceName } from "./lineVoice";

/**
 * Выбор голоса: сетка голосов с ▶. Общая для окна звука сцены и окна голоса героя —
 * голос выбирается в обоих одинаково, а послушать его можно и на самой карточке сцены.
 */

export type Voice = {
  id: string;
  name: string;
  gender: string;
  age: string;
  accent: string;
  description: string;
  use_case: string;
  preview: string;
};

/** Перевод подписи голоса: незнакомое слово возвращается как есть (defaultValue). */
type Tr = (key: string, options: { defaultValue: string }) => string;

/** Голоса из каталога: читаем, когда окно открылось, и держим, пока оно живёт. */
export function useVoices(open: boolean): Voice[] {
  const [voices, setVoices] = useState<Voice[]>([]);
  useEffect(() => {
    if (!open || voices.length) return;
    void (async () => {
      const res = await fetchData<Voice[]>("cartoon/audio/voices/", "GET", undefined, false);
      if (res.ok && Array.isArray(res.data)) setVoices(res.data);
    })();
  }, [open, voices.length]);
  return voices;
}

export type VoicePreview = {
  /** id голоса, который сейчас звучит (или загружается). */
  previewing: string | null;
  play: (voice: { id: string; preview?: string }) => void;
  stop: () => void;
};

/** Пример голоса. Клиент: он должен звучать по-русски — родной образец у
 *  провайдера английский, и по нему не понять, как заговорит герой. */
export function useVoicePreview(): VoicePreview {
  const { i18n } = useTranslation("common");
  const audioRef = useRef<HTMLAudioElement | null>(null);
  // Номер нажатия: нажали другой голос, пока первый грузился, — первый звучать уже не должен.
  const pressRef = useRef(0);
  const [previewing, setPreviewing] = useState<string | null>(null);

  const stop = useCallback(() => {
    pressRef.current += 1;
    audioRef.current?.pause();
    setPreviewing(null);
  }, []);

  // Окно закрыли посреди прослушивания — звук не должен играть дальше.
  useEffect(
    () => () => {
      pressRef.current += 1;
      audioRef.current?.pause();
    },
    []
  );

  const play = useCallback(
    async (voice: { id: string; preview?: string }) => {
      if (previewing === voice.id) {
        stop();
        return;
      }
      audioRef.current?.pause();
      pressRef.current += 1;
      const press = pressRef.current;
      setPreviewing(voice.id);
      const lang = (i18n.language || "ru").slice(0, 2);
      const res = await fetchData<{ url: string }>(
        `cartoon/audio/voices/${encodeURIComponent(voice.id)}/preview/?lang=${lang === "ky" ? "kg" : lang}`,
        "GET", undefined, false
      );
      if (press !== pressRef.current) return;
      const src = (res.ok && res.data?.url) || voice.preview;
      if (!src) {
        setPreviewing(null);
        return;
      }
      const a = new Audio(src);
      audioRef.current = a;
      a.onended = () => setPreviewing(null);
      void a.play().catch(() => setPreviewing(null));
    },
    [previewing, stop, i18n.language]
  );

  return { previewing, play: (voice) => void play(voice), stop };
}

/**
 * Подпись голоса на языке человека.
 *
 * ElevenLabs размечает голоса по-английски («female · middle_aged ·
 * professional»), и в русском интерфейсе это выглядит как служебный вывод.
 * Переводим то, что знаем, а незнакомое слово показываем как есть.
 */
/** Характер голоса по-русски: «мягкий, тёплый». Для известных голосов —
 *  написанное руками описание, для остальных — перевод слов из названия. */
function voiceCharacter(v: Voice, t: Tr): string {
  const key = shortVoiceName(v.name).toLowerCase().replace(/[^a-z]+/g, "");
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

export default function VoicePicker({
  voices,
  value,
  onChange,
  preview,
  className = "max-h-44 sm:grid-cols-2",
}: {
  voices: Voice[];
  value: string;
  onChange: (voiceId: string) => void;
  preview: VoicePreview;
  /** Высота и колонки сетки: в окне поменьше голосу нужна вся ширина. */
  className?: string;
}) {
  const { t } = useTranslation("common");
  return (
    <div className={vx("grid grid-cols-1 gap-1.5 overflow-y-auto pr-1", className)}>
      {voices.length === 0 && <span className="text-xs text-muted-2">{t("studio_ui.audio_loading")}</span>}
      {voices.map((v) => (
        <div
          key={v.id}
          className={vx(
            "flex items-center gap-2 rounded-xl border px-1.5 py-1 transition-colors",
            value === v.id ? "border-vs-accent/45 bg-accent/[0.1]" : "border-vs-ink/10 hover:border-vs-ink/20",
          )}
        >
          <button
            type="button"
            onClick={() => preview.play(v)}
            aria-label={`${t("studio_ui.audio_listen")}: ${shortVoiceName(v.name)}`}
            aria-pressed={preview.previewing === v.id}
            title={t("studio_ui.audio_listen")}
            className={vx(
              "grid size-11 shrink-0 cursor-pointer place-items-center rounded-full bg-vs-ink/[0.06] text-foreground transition-colors hover:bg-vs-ink/[0.1] disabled:opacity-40 md:size-8",
              VS_FOCUS,
            )}
          >
            {preview.previewing === v.id ? <FiPause aria-hidden /> : <FiPlay aria-hidden />}
          </button>
          <button
            type="button"
            onClick={() => onChange(v.id)}
            aria-pressed={value === v.id}
            className={vx("min-h-11 min-w-0 flex-1 cursor-pointer rounded-lg px-1 text-left md:min-h-9", VS_FOCUS)}
          >
            <div className="truncate text-sm text-foreground">
              <span className="font-semibold">{shortVoiceName(v.name)}</span>
              <span className="text-muted"> — {voiceCharacter(v, t)}</span>
            </div>
            <div className="truncate text-[10px] text-muted-2">{voiceTraits(v, t)}</div>
          </button>
        </div>
      ))}
    </div>
  );
}
