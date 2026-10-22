"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiLoader, FiMic, FiPause, FiPlay, FiRefreshCw } from "react-icons/fi";
import { apiLang } from "@/lib/apiLang";
import { VS_BTN_GHOST, VS_BTN_LINK, VS_FOCUS, VS_LABEL, vx } from "@/components/vstudio/ui/skin";
import { CS_SKELETON } from "@/components/studio/ui/cartoonSkin";
import {
  effectiveStart,
  startOptions,
  textChars,
  trackErrorText,
  voiceCutS,
  voiceNameKey,
  voiceRefusal,
  voiceShortName,
  voiceTailWords,
  voiceWait,
  voiceWordKey,
  type StartOption,
} from "./audioLogic";
import { voicePreview } from "./mergeApi";
import { formatDuration, type LocalItem } from "./mergeLogic";
import type { MergeVoice } from "./mergeTypes";
import {
  SOUND_PAID_BTN,
  SOUND_SELECT,
  SOUND_SPIN,
  SOUND_TEXT_FIELD,
  SOUND_TRACK,
  SoundBlock,
  SoundChip,
  SoundError,
  SoundPending,
  SoundRemove,
  VolumeSlider,
  keepFocus,
  useSay,
  useTrackMeta,
} from "./soundUi";
import type { MergeAudioModel } from "./useMergeAudio";

/**
 * «Голос за кадром»: голос ElevenLabs из общего списка мультстудии (▶ —
 * пример на языке страницы), текст со счётчиком, «Начать с фрагмента N» и
 * «Озвучить · N кр» — цена считается на месте по той же формуле, что у
 * сервера. Готовый голос — плеер, начало, громкость, «Заменить» и «Убрать».
 */
export default function SoundVoice({ audio, items }: { audio: MergeAudioModel; items: readonly LocalItem[] }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const say = useSay();
  const meta = useTrackMeta();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const pickId = useId();
  const textId = useId();
  const countId = useId();
  const startId = useId();
  const readyStartId = useId();
  const hintId = useId();

  const { voice, draft, editable, configured, limits, voices } = audio;
  const { loadVoices } = audio.actions;
  const busy = audio.voiceBusy;
  const ready = voice.ready;
  const replacing = Boolean(ready) && audio.forms.voice;
  const showForm = editable && configured && !voice.pending && (!ready || audio.forms.voice);

  // Список голосов — когда форма на экране впервые; дальше он живёт в модели.
  const needVoices = showForm && !voices.loaded && !voices.loading;
  useEffect(() => {
    if (needVoices) void loadVoices();
  }, [needVoices, loadVoices]);

  const untitled = t("merge.untitled", { defaultValue: "Без названия" });
  const optionLabel = (o: StartOption) =>
    t("merge.audio.voice.option", {
      defaultValue: "№{{n}} · с {{time}} — {{title}}",
      n: o.n,
      time: formatDuration(o.at),
      title: o.title || untitled,
    });
  const options = startOptions(items);
  const credits = (n: number) => t("top.balance", { defaultValue: "{{n}} кр", n });
  const chars = textChars(draft.text);
  const over = chars > limits.voice_chars;
  const refusal = voiceRefusal(draft.text, draft.voiceId, limits);
  // Сведение режет звук по концу картинки: длинный голос с позднего фрагмента обрежется — говорим заранее.
  const cut = ready ? voiceCutS(ready.duration_s, audio.voiceStart, items) : 0;
  // Длинный текст ElevenLabs читает дольше: «несколько секунд» для 2000 символов — неправда.
  const waitLong = voiceWait(busy ? draft.text : voice.pending?.text) === "long";

  const run = () => {
    if (busy) return;
    if (refusal) {
      textRef.current?.focus();
      return;
    }
    audio.actions.makeVoice();
  };

  const chip =
    busy || voice.pending ? (
      <SoundChip tone="busy">{t("merge.audio.chipMaking", { defaultValue: "Делается…" })}</SoundChip>
    ) : ready ? (
      <SoundChip tone="ready">{t("merge.audio.chipReady", { defaultValue: "Готово" })}</SoundChip>
    ) : null;

  const hint = busy
    ? waitLong
      ? t("merge.audio.voice.runningHintLong", { defaultValue: "Текст длинный — это может занять до минуты." })
      : t("merge.audio.voice.runningHint", { defaultValue: "Обычно это несколько секунд." })
    : refusal
      ? say(refusal)
      : replacing
        ? t("merge.audio.voice.replaceNote", {
            defaultValue: "Новый голос заменит прежний, когда будет готов. Спишется цена на кнопке.",
          })
        : "";

  return (
    <SoundBlock
      icon={FiMic}
      title={t("merge.audio.voice.title", { defaultValue: "Голос за кадром" })}
      chip={chip}
      headingRef={headingRef}
      sub={t("merge.audio.voice.sub", { defaultValue: "ИИ прочитает ваш текст поверх роликов — с выбранного фрагмента." })}
    >
      {audio.errors.voice && (
        <SoundError
          text={say(audio.errors.voice)}
          onClose={() => {
            audio.actions.dismissError("voice");
            // Неудачная попытка осталась на сервере плашкой — скрываем её вместе с отказом, одним нажатием.
            if (voice.failed) void audio.actions.removeTrack(voice.failed);
            keepFocus(headingRef);
          }}
        />
      )}
      {/* Отказ на нажатие уже сказал то же самое — вторая плашка про ту же дорожку не нужна. */}
      {voice.failed && !busy && !audio.errors.voice && (
        <SoundError
          alert={false}
          text={say(trackErrorText(voice.failed))}
          busy={audio.deleting === voice.failed.id}
          onClose={() => {
            const failed = voice.failed;
            if (failed) void audio.actions.removeTrack(failed).then(() => keepFocus(headingRef));
          }}
        />
      )}
      {voice.pending && !busy && (
        <SoundPending>
          {waitLong
            ? t("merge.audio.voice.pendingLong", { defaultValue: "Голос озвучивается — длинный текст может занять до минуты." })
            : t("merge.audio.voice.pending", { defaultValue: "Голос озвучивается — обычно это несколько секунд." })}
        </SoundPending>
      )}

      {ready && (
        <div className={SOUND_TRACK}>
          <p className="line-clamp-4 break-words text-sm leading-snug text-foreground">{ready.text}</p>
          <p className="text-xs tabular-nums text-muted">{[ready.voice_name, meta(ready, editable)].filter(Boolean).join(" · ")}</p>
          <audio
            controls
            preload="none"
            src={ready.url ?? undefined}
            className="h-10 w-full"
            aria-label={t("merge.audio.voice.play", { defaultValue: "Послушать голос за кадром" })}
          />
          {cut > 0 && (
            <p className="text-xs leading-snug text-muted">
              {t("merge.audio.voice.cut", {
                defaultValue: "Голос длиннее, чем осталось ролика с этого фрагмента: последние {{time}} не прозвучат.",
                time: formatDuration(Math.max(1, cut)),
              })}
            </p>
          )}
          {editable && !replacing ? (
            <>
              {options.length > 0 && (
                <div className="flex flex-col gap-1.5">
                  <label htmlFor={readyStartId} className={VS_LABEL}>
                    {t("merge.audio.voice.start", { defaultValue: "Начать с фрагмента" })}
                  </label>
                  <select
                    id={readyStartId}
                    value={audio.voiceStart}
                    onChange={(e) => audio.actions.moveVoice(Number(e.currentTarget.value))}
                    className={SOUND_SELECT}
                  >
                    {options.map((o) => (
                      <option key={o.index} value={o.index}>
                        {optionLabel(o)}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <VolumeSlider
                label={t("merge.audio.voice.volume", { defaultValue: "Громкость голоса" })}
                value={audio.voiceVolume}
                max={limits.voice_volume_max}
                onChange={audio.actions.setVoiceVolume}
              />
              <div className="-ml-2 flex flex-wrap items-center gap-x-1">
                {configured && (
                  <button type="button" onClick={() => audio.actions.openForm("voice", ready)} className={VS_BTN_LINK}>
                    <FiRefreshCw aria-hidden="true" />
                    {t("merge.audio.replace", { defaultValue: "Заменить" })}
                  </button>
                )}
                <SoundRemove
                  label={t("merge.audio.remove", { defaultValue: "Убрать" })}
                  ask={t("merge.audio.voice.removeAsk", {
                    defaultValue: "Убрать голос за кадром? Он оплачен — новый будет стоить заново.",
                  })}
                  busy={audio.deleting === ready.id}
                  onRemove={() => void audio.actions.removeTrack(ready).then(() => keepFocus(headingRef))}
                />
              </div>
            </>
          ) : (
            !editable && (
              <p className="text-xs text-muted">
                {t("merge.audio.voice.from", { defaultValue: "С фрагмента №{{n}}", n: audio.voiceStart + 1 })}
              </p>
            )
          )}
        </div>
      )}

      {showForm && (
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <span id={pickId} className={VS_LABEL}>
              {t("merge.audio.voice.pick", { defaultValue: "Голос" })}
            </span>
            <VoicePicker
              voices={voices}
              selected={draft.voiceId}
              labelId={pickId}
              onSelect={audio.actions.setVoiceId}
              onRetry={() => void loadVoices()}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={textId} className={VS_LABEL}>
              {t("merge.audio.voice.text", { defaultValue: "Текст" })}
            </label>
            <textarea
              ref={textRef}
              id={textId}
              rows={4}
              value={draft.text}
              onChange={(e) => audio.actions.setText(e.currentTarget.value)}
              placeholder={t("merge.audio.voice.placeholder", {
                defaultValue: "Что скажет голос за кадром? Например: «Это было лучшее лето в нашей жизни».",
              })}
              aria-describedby={countId}
              aria-invalid={over || undefined}
              className={SOUND_TEXT_FIELD}
            />
            <p id={countId} className={vx("text-xs tabular-nums", over ? "text-status-fail" : "text-muted-2")}>
              {t("merge.audio.chars", { defaultValue: "{{n}} из {{max}} символов", n: chars, max: limits.voice_chars })}
            </p>
          </div>
          {options.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <label htmlFor={startId} className={VS_LABEL}>
                {t("merge.audio.voice.start", { defaultValue: "Начать с фрагмента" })}
              </label>
              <select
                id={startId}
                value={effectiveStart(draft.start, items.length)}
                onChange={(e) => audio.actions.setStart(Number(e.currentTarget.value))}
                className={SOUND_SELECT}
              >
                {options.map((o) => (
                  <option key={o.index} value={o.index}>
                    {optionLabel(o)}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={run}
              aria-disabled={busy || Boolean(refusal) || undefined}
              aria-busy={busy || undefined}
              aria-describedby={hint ? hintId : undefined}
              className={vx(SOUND_PAID_BTN, busy && "!cursor-wait")}
            >
              {busy ? <FiLoader className={SOUND_SPIN} aria-hidden="true" /> : <FiMic aria-hidden="true" />}
              {busy
                ? t("merge.audio.voice.running", { defaultValue: "Озвучиваю…" })
                : t("merge.audio.voice.run", { defaultValue: "Озвучить · {{price}}", price: credits(audio.voicePrice) })}
            </button>
            {replacing && !busy && (
              <button type="button" onClick={() => audio.actions.closeForm("voice")} className={VS_BTN_GHOST}>
                {t("nav.cancel", { defaultValue: "Отмена" })}
              </button>
            )}
          </div>
          {hint && (
            <p id={hintId} className="text-xs leading-snug text-muted">
              {hint}
            </p>
          )}
        </div>
      )}

      {!configured && !ready && (
        <p className="text-[13px] leading-snug text-muted">
          {t("merge.audio.voice.off", { defaultValue: "Голос за кадром пока не подключён." })}
        </p>
      )}
    </SoundBlock>
  );
}

type VoicesView = MergeAudioModel["voices"];

/**
 * Выбор голоса: радиокнопки (стрелки переключают, как у любой группы) и ▶ у
 * каждого — пример на языке страницы. Характер голоса — словарём мультстудии:
 * ElevenLabs размечает голоса по-английски.
 */
function VoicePicker({
  voices,
  selected,
  labelId,
  onSelect,
  onRetry,
}: {
  voices: VoicesView;
  selected: string;
  labelId: string;
  onSelect: (id: string) => void;
  onRetry: () => void;
}) {
  const { t, i18n } = useTranslation("vstudio", { useSuspense: false });
  const name = useId();
  const player = useRef<HTMLAudioElement | null>(null);
  const request = useRef(0);
  const [playing, setPlaying] = useState<string | null>(null);
  const [fetching, setFetching] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  // Панель закрыли посреди примера — звук не должен играть дальше.
  useEffect(
    () => () => {
      request.current += 1;
      player.current?.pause();
    },
    [],
  );

  const stop = () => {
    request.current += 1;
    player.current?.pause();
    player.current = null;
    setPlaying(null);
    setFetching(null);
  };

  const play = async (v: MergeVoice) => {
    if (playing === v.id || fetching === v.id) {
      stop();
      return;
    }
    stop();
    const req = request.current;
    setFailed(null);
    setFetching(v.id);
    const res = await voicePreview(v.id, apiLang(i18n.language));
    if (req !== request.current) return;
    setFetching(null);
    // Пример на языке страницы не готов — родной образец провайдера лучше, чем ничего.
    const src = (res.ok && res.data.url) || v.preview;
    if (!src) {
      setFailed(v.id);
      return;
    }
    const a = new Audio(src);
    player.current = a;
    a.onended = () => {
      if (player.current === a) setPlaying(null);
    };
    a.onerror = () => {
      if (player.current !== a) return;
      setPlaying(null);
      setFailed(v.id);
    };
    setPlaying(v.id);
    try {
      await a.play();
    } catch {
      if (player.current === a) setPlaying(null);
    }
  };

  const character = (v: MergeVoice): string => {
    const known = t(`studio_ui.voice_n_${voiceNameKey(v)}`, { ns: "common", defaultValue: "" });
    if (known) return known;
    return voiceTailWords(v)
      .map((w) => t(`studio_ui.voice_w_${voiceWordKey(w)}`, { ns: "common", defaultValue: w }))
      .join(", ");
  };
  const traits = (v: MergeVoice): string =>
    [v.gender, v.age]
      .filter(Boolean)
      .map((w) => t(`studio_ui.voice_w_${voiceWordKey(w)}`, { ns: "common", defaultValue: w }))
      .join(" · ");

  if (!voices.loaded || (voices.loading && voices.list.length === 0)) {
    return (
      <div className="grid gap-1.5" aria-busy="true">
        <span className="sr-only">{t("merge.audio.voice.loading", { defaultValue: "Загружаем голоса…" })}</span>
        {[0, 1, 2].map((i) => (
          <div key={i} className={vx("h-12 animate-pulse rounded-xl motion-reduce:animate-none", CS_SKELETON)} aria-hidden="true" />
        ))}
      </div>
    );
  }
  if (voices.failed && voices.list.length === 0) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-[13px] text-muted">
        <span>{t("merge.audio.voice.listFailed", { defaultValue: "Голоса не загрузились." })}</span>
        <button type="button" onClick={onRetry} className={VS_BTN_LINK}>
          <FiRefreshCw aria-hidden="true" />
          {t("page.retry", { defaultValue: "Попробовать снова" })}
        </button>
      </div>
    );
  }
  if (voices.list.length === 0) {
    return (
      <p className="text-[13px] leading-snug text-muted">
        {t("merge.audio.voice.listEmpty", { defaultValue: "Голосов пока нет — озвучка временно недоступна." })}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div
        role="radiogroup"
        aria-labelledby={labelId}
        className="grid max-h-60 gap-1.5 overflow-y-auto overscroll-contain p-0.5 pr-1"
      >
        {voices.list.map((v) => {
          const on = v.id === selected;
          const short = voiceShortName(v);
          const about = character(v);
          const kind = traits(v);
          const isPlaying = playing === v.id;
          const isFetching = fetching === v.id;
          return (
            <div
              key={v.id}
              className={vx(
                "flex items-center gap-1.5 rounded-xl border p-1 transition-colors has-[input:focus-visible]:ring-2 has-[input:focus-visible]:ring-vs-accent/80",
                on ? "border-vs-accent/45 bg-accent/[0.1]" : "border-vs-ink/10 hover:border-vs-ink/20",
              )}
            >
              <button
                type="button"
                onClick={() => void play(v)}
                aria-label={
                  isPlaying || isFetching
                    ? t("merge.audio.voice.stop", { defaultValue: "Остановить пример: {{name}}", name: short })
                    : t("merge.audio.voice.listen", { defaultValue: "Послушать пример: {{name}}", name: short })
                }
                aria-pressed={isPlaying}
                className={vx(
                  "grid size-11 shrink-0 cursor-pointer place-items-center rounded-full bg-vs-ink/[0.06] text-foreground transition-colors hover:bg-vs-ink/[0.1] md:size-9",
                  VS_FOCUS,
                )}
              >
                {isFetching ? (
                  <FiLoader className={SOUND_SPIN} aria-hidden="true" />
                ) : isPlaying ? (
                  <FiPause aria-hidden="true" />
                ) : (
                  <FiPlay aria-hidden="true" />
                )}
              </button>
              <label className="flex min-h-11 min-w-0 flex-1 cursor-pointer flex-col justify-center px-1 md:min-h-9">
                <input
                  type="radio"
                  name={name}
                  value={v.id}
                  checked={on}
                  onChange={() => onSelect(v.id)}
                  className="sr-only"
                />
                <span className="truncate text-sm text-foreground">
                  <span className="font-semibold">{short}</span>
                  {about && <span className="text-muted"> — {about}</span>}
                </span>
                {kind && <span className="truncate text-[11px] text-muted-2">{kind}</span>}
              </label>
            </div>
          );
        })}
      </div>
      {failed && (
        <p role="status" className="text-xs text-muted">
          {t("merge.audio.voice.previewFailed", { defaultValue: "Пример голоса пока недоступен." })}
        </p>
      )}
    </div>
  );
}
