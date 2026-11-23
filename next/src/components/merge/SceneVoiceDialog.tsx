"use client";

import { useEffect, useId, useRef, useState, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import { FiAlertCircle, FiCrosshair, FiLoader, FiMic } from "react-icons/fi";
import { Modal } from "@/components/dialog/Dialog";
import { VS_BTN_LINK, VS_FOCUS, VS_INPUT, VS_LABEL, VS_MEDIA, vx } from "@/components/vstudio/ui/skin";
import { CS_NOTE_GOLD } from "@/components/studio/ui/cartoonSkin";
import {
  clampStart,
  lineMaxStart,
  lineOverflowS,
  lineRefusal,
  linesOf,
  liveLineCount,
  parseSecond,
  roundSecond,
  textChars,
  trackErrorText,
  voicePrice,
} from "./audioLogic";
import { formatDuration, refusalText, type LocalItem } from "./mergeLogic";
import type { MergeLine } from "./mergeTypes";
import { VoicePicker } from "./SoundVoice";
import {
  SOUND_PAID_BTN,
  SOUND_SPIN,
  SOUND_TEXT_FIELD,
  SOUND_TRACK,
  SoundError,
  SoundPending,
  SoundRemove,
  VolumeSlider,
  useSay,
  useSeconds,
  useTrackMeta,
} from "./soundUi";
import type { MergeAudioModel } from "./useMergeAudio";

/**
 * «Голос сцены» — окно фрагмента склейки, как «Звук сцены» в мультстудии: видео
 * фрагмента, текст, голос, секунда начала и громкость. Секунду можно взять с
 * плеера («Поставить на текущую секунду»), набрать числом или ползунком — с
 * точностью до 0,1 с. Готовые голоса фрагмента ниже: послушать, сдвинуть,
 * сделать тише или громче (бесплатно, уходит на сервер, когда палец
 * остановился), убрать. Цена на кнопке — та же формула, что у голоса за кадром;
 * списывается, только когда голос готов.
 */

/** Ползунок секунды и громкости: на сервер — когда палец остановился. */
const PATCH_DEBOUNCE_MS = 350;

export type SceneVoiceDialogProps = {
  open: boolean;
  item: LocalItem | null;
  /** Номер фрагмента с нуля. */
  index: number;
  /** Фрагмент последний: голос за концом ролика обрежется, а не зайдёт на следующую сцену. */
  last: boolean;
  audio: MergeAudioModel;
  onClose: () => void;
};

export default function SceneVoiceDialog({ open, item, index, last, audio, onClose }: SceneVoiceDialogProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const title = t("merge.line.dialogTitle", { defaultValue: "Голос сцены · фрагмент №{{n}}", n: index + 1 });
  return (
    // Окно длинное (видео, голоса, форма): Tab не уходит на страницу под ним — к «Склеить» и ✕ ленты.
    <Modal
      open={open && item !== null}
      onClose={onClose}
      title={title}
      size="lg"
      mobileFull
      trapFocus
      closeLabel={t("mobile.close", { defaultValue: "Закрыть" })}
    >
      {item && <SceneVoiceBody item={item} last={last} audio={audio} />}
    </Modal>
  );
}

function SceneVoiceBody({ item, last, audio }: { item: LocalItem; last: boolean; audio: MergeAudioModel }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const say = useSay();
  const videoRef = useRef<HTMLVideoElement>(null);
  const headRef = useRef<HTMLParagraphElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const pickId = useId();
  const textId = useId();
  const countId = useId();
  const hintId = useId();

  const key = item.key;
  const duration = typeof item.duration_s === "number" && item.duration_s > 0 ? item.duration_s : 0;
  const lim = audio.lineLimits;
  const lines = linesOf(audio.lines, key);
  const busy = audio.lineBusy === key;
  /** Озвучивается голос другого фрагмента: заказы голоса сцены — по одному. */
  const otherBusy = audio.lineBusy !== null && !busy;
  const error = audio.lineError && audio.lineError.key === key ? audio.lineError.text : null;
  const { voices, editable, configured } = audio;
  const { loadVoices } = audio.actions;

  const [text, setText] = useState("");
  const [start, setStart] = useState(0);
  const [volume, setVolume] = useState(1);
  // Голос, выбранный в этом окне в прошлый раз (у склейки свой), — если он ещё есть в списке;
  // иначе — голос черновика голоса за кадром.
  const remembered = audio.lineVoiceId;
  const knownVoice = !voices.loaded || voices.list.some((v) => v.id === remembered);
  const chosenVoice = (knownVoice && remembered) || audio.draft.voiceId;

  const count = liveLineCount(audio.lines, key);
  const full = count >= lim.lines_per_fragment;
  // Ролик фрагмента удалён или не готов: голос к нему не заказать (сервер тоже откажет).
  const unavailable = !item.available;
  const showForm = editable && configured && !full && !unavailable;

  // Окно открылось — фокус на подпись фрагмента: экранная клавиатура телефона не выскакивает сама.
  useEffect(() => {
    headRef.current?.focus({ preventScroll: true });
  }, []);

  // Отказ сервера (сбой озвучки, «уже делается», цена сменилась, связь) — в поле зрения:
  // на телефоне окно во весь экран, и плашка иначе могла бы оказаться за краем.
  useEffect(() => {
    if (error) errorRef.current?.scrollIntoView({ block: "nearest" });
  }, [error]);

  const needVoices = showForm && !voices.loaded && !voices.loading;
  useEffect(() => {
    if (needVoices) void loadVoices();
  }, [needVoices, loadVoices]);

  const chars = textChars(text);
  const over = chars > lim.line_chars;
  const price = voicePrice(text, audio.prices);
  const refusal = lineRefusal(text, chosenVoice, {
    chars: lim.line_chars,
    count,
    perFragment: lim.lines_per_fragment,
    total: liveLineCount(audio.lines),
    max: lim.lines_max,
  });
  const credits = (n: number) => t("top.balance", { defaultValue: "{{n}} кр", n });
  const fragmentTitle = item.title.trim() || t("merge.untitled", { defaultValue: "Без названия" });

  const now = (): number => clampStart(videoRef.current?.currentTime ?? 0, duration);

  const run = async () => {
    if (busy || otherBusy) return;
    if (refusal) {
      textRef.current?.focus();
      return;
    }
    const done = await audio.actions.makeLine({ fragmentKey: key, text, voiceId: chosenVoice, start, volume });
    if (done) {
      setText("");
      // Следующий голос этой сцены обычно идёт позже — секунда остаётся, где была.
    }
  };

  const hint = busy
    ? t("merge.line.runningHint", { defaultValue: "Обычно это несколько секунд." })
    : otherBusy
      ? t("merge.line.otherBusy", {
          defaultValue: "Сейчас озвучивается голос другого фрагмента — дождитесь его, потом озвучьте этот.",
        })
      : refusal && chars > 0
      ? say(refusal)
      : "";

  return (
    <div className="flex flex-col gap-4">
      <p ref={headRef} tabIndex={-1} className="text-xs leading-snug text-muted-2 focus:outline-none">
        {t("merge.line.about", {
          defaultValue: "{{title}} · {{time}}",
          title: fragmentTitle,
          time: formatDuration(duration),
        })}
        <span className="mt-1 block text-[13px] text-muted">
          {t("merge.line.sub", {
            defaultValue: "ИИ прочитает текст поверх этого фрагмента — с той секунды, которую вы выберете.",
          })}
        </span>
      </p>

      <div className={vx(VS_MEDIA, "aspect-video max-h-[38vh] w-full")}>
        {item.available && item.url ? (
          <video
            ref={videoRef}
            src={item.url}
            poster={item.poster ?? undefined}
            controls
            playsInline
            preload="metadata"
            className="h-full w-full object-contain"
            aria-label={t("merge.line.preview", { defaultValue: "Видео фрагмента" })}
          />
        ) : (
          // Видео недоступно — без плеера: секунду можно задать числом.
          <div className="grid h-full place-items-center p-4 text-center text-[13px] text-white/80">
            {t("merge.tl.unavailable", { defaultValue: "Видео недоступно — уберите его из склейки" })}
          </div>
        )}
      </div>

      {!editable && audio.state?.edit_block && (
        <p role="status" className={vx(CS_NOTE_GOLD, "!px-3 !py-2.5 !text-[13px] leading-snug")}>
          {say(refusalText(audio.state.edit_block.error_code, {}, audio.state.edit_block.error))}
        </p>
      )}
      {editable && !configured && (
        <p className={vx(CS_NOTE_GOLD, "!px-3 !py-2.5 !text-[13px] leading-snug")}>
          {t("merge.line.off", { defaultValue: "Голос сцены пока не подключён." })}
        </p>
      )}
      {/* Без формы (голосов на фрагменте уже предел, звук не правится) — отказ здесь, наверху. */}
      {error && !showForm && (
        <div ref={errorRef}>
          <SoundError text={say(error)} onClose={audio.actions.dismissLineError} />
        </div>
      )}

      {lines.length > 0 && (
        <section aria-labelledby={`${pickId}-list`} className="flex flex-col gap-2">
          <h3 id={`${pickId}-list`} className={VS_LABEL}>
            {t("merge.line.list", { defaultValue: "Голоса этого фрагмента" })}
          </h3>
          {lines.map((line) => (
            <LineRow
              key={line.id}
              line={line}
              audio={audio}
              duration={duration}
              last={last}
              hasVideo={Boolean(item.available && item.url)}
              videoRef={videoRef}
              headRef={headRef}
            />
          ))}
        </section>
      )}

      {editable && configured && unavailable && (
        <p className={vx(CS_NOTE_GOLD, "!px-3 !py-2.5 !text-[13px] leading-snug")}>
          {say(refusalText("line_unavailable"))}
        </p>
      )}
      {editable && configured && full && !unavailable && (
        <p className="text-[13px] leading-snug text-muted">
          {say(refusalText("line_fragment_full", { max: lim.lines_per_fragment }))}
        </p>
      )}

      {showForm && (
        <section aria-label={t("merge.line.new", { defaultValue: "Новый голос" })} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <span id={pickId} className={VS_LABEL}>
              {t("merge.audio.voice.pick", { defaultValue: "Голос" })}
            </span>
            <VoicePicker
              voices={voices}
              selected={chosenVoice}
              labelId={pickId}
              onSelect={audio.actions.setLineVoice}
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
              rows={3}
              value={text}
              onChange={(e) => setText(e.currentTarget.value)}
              placeholder={t("merge.line.placeholder", {
                defaultValue: "Что скажет голос в этой сцене? Например: «Смотри, как высоко!»",
              })}
              aria-describedby={countId}
              aria-invalid={over || undefined}
              className={SOUND_TEXT_FIELD}
            />
            <p id={countId} className={vx("text-xs tabular-nums", over ? "text-status-fail" : "text-muted-2")}>
              {t("merge.audio.chars", { defaultValue: "{{n}} из {{max}} символов", n: chars, max: lim.line_chars })}
            </p>
          </div>
          <StartField
            value={start}
            duration={duration}
            onChange={setStart}
            onNow={item.available && item.url ? () => setStart(now()) : undefined}
          />
          <VolumeSlider
            label={t("merge.line.volume", { defaultValue: "Громкость" })}
            value={volume}
            max={lim.line_volume_max}
            onChange={setVolume}
          />
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void run()}
              aria-disabled={busy || otherBusy || Boolean(refusal) || undefined}
              aria-busy={busy || undefined}
              aria-describedby={hint ? hintId : undefined}
              className={vx(SOUND_PAID_BTN, (busy || otherBusy) && "!cursor-wait")}
            >
              {busy ? <FiLoader className={SOUND_SPIN} aria-hidden="true" /> : <FiMic aria-hidden="true" />}
              {busy
                ? t("merge.audio.voice.running", { defaultValue: "Озвучиваю…" })
                : t("merge.audio.voice.run", { defaultValue: "Озвучить · {{price}}", price: credits(price) })}
            </button>
          </div>
          {/* Отказ «Озвучить» — прямо под кнопкой: туда человек и смотрит после нажатия. */}
          {error && (
            <div ref={errorRef}>
              <SoundError text={say(error)} onClose={audio.actions.dismissLineError} />
            </div>
          )}
          {hint && (
            <p id={hintId} className="text-xs leading-snug text-muted">
              {hint}
            </p>
          )}
          <p className="text-xs leading-snug text-muted-2">
            {t("merge.line.money", {
              defaultValue:
                "Цена — как у голоса за кадром: спишется, только когда голос готов. Секунду и громкость потом можно менять бесплатно.",
            })}
          </p>
        </section>
      )}

      {/* Окно модальное: диктор слышит только его — готовность голоса говорим и здесь. */}
      <p className="sr-only" role="status" aria-live="polite">
        {audio.said}
      </p>
    </div>
  );
}

/**
 * Секунда начала: число (шаг 0,1), ползунок и «Поставить на текущую секунду» (с плеера).
 * Поле можно стирать и набирать — в пределы фрагмента значение приводится, когда поле
 * отпустили (blur, Enter), а ползунок и кнопка дают его сразу.
 */
function StartField({
  value,
  duration,
  onChange,
  onNow,
  compact = false,
}: {
  value: number;
  duration: number;
  onChange: (v: number) => void;
  onNow?: () => void;
  compact?: boolean;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { num, sec } = useSeconds();
  const numberId = useId();
  const rangeId = useId();
  const hintId = useId();
  const max = lineMaxStart(duration);
  const [typed, setTyped] = useState<string | null>(null);
  const shown = typed ?? num(value);

  // Пусто или не число — прежнее значение остаётся (а не 0); «2,5» и «2.5» — одно и то же.
  const commit = () => {
    if (typed === null) return;
    const v = parseSecond(typed);
    setTyped(null);
    if (v !== null) onChange(clampStart(v, duration));
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <label htmlFor={numberId} className={VS_LABEL}>
          {t("merge.line.start", { defaultValue: "С секунды" })}
        </label>
        <span id={hintId} className="text-[11px] tabular-nums text-muted-2">
          {t("merge.line.startHint", { defaultValue: "от 0 до {{max}} с", max: num(max) })}
        </span>
      </div>
      <div className="flex min-w-0 items-center gap-2">
        {/* Текстом, а не type=number: там «2,5» в части браузеров читается как пустое поле. */}
        <input
          id={numberId}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          value={shown}
          aria-describedby={hintId}
          onChange={(e) => {
            const raw = e.currentTarget.value;
            setTyped(raw);
            const v = parseSecond(raw);
            // Набранное в пределах — сразу в ползунок; за пределами — приведём, когда поле отпустят.
            if (v !== null && v >= 0 && v <= max) onChange(roundSecond(v));
          }}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commit();
            }
          }}
          // !w-24: в VS_INPUT стоит w-full, а vx классы не сливает — без ! поле съедало ползунок.
          className={vx(VS_INPUT, "!w-24 shrink-0 tabular-nums max-sm:!text-base")}
        />
        <input
          id={rangeId}
          type="range"
          min={0}
          max={max}
          step={0.1}
          value={Math.min(max, value)}
          disabled={max <= 0}
          aria-label={t("merge.line.start", { defaultValue: "С секунды" })}
          aria-valuetext={sec(value)}
          onChange={(e) => {
            setTyped(null);
            onChange(roundSecond(Number(e.currentTarget.value)));
          }}
          className={vx("h-11 min-w-0 flex-1 cursor-pointer rounded-full accent-[var(--accent)] md:h-8", VS_FOCUS)}
        />
      </div>
      {onNow && (
        <button
          type="button"
          onClick={() => {
            setTyped(null);
            onNow();
          }}
          // Высота — от VS_BTN_LINK: 44 px на телефоне, как остальные кнопки склейки.
          className={vx(VS_BTN_LINK, "-ml-2 self-start", compact && "!text-[13px]")}
        >
          <FiCrosshair aria-hidden="true" />
          {t("merge.line.now", { defaultValue: "Поставить на текущую секунду" })}
        </button>
      )}
    </div>
  );
}

/**
 * Готовый (или делающийся) голос фрагмента: текст, плеер, секунда и громкость, предупреждение
 * о заходе на следующую сцену, «Убрать». Секунда и громкость уходят на сервер, когда палец
 * остановился; окно закрыли раньше — правка уходит сразу.
 */
function LineRow({
  line,
  audio,
  duration,
  last,
  hasVideo,
  videoRef,
  headRef,
}: {
  line: MergeLine;
  audio: MergeAudioModel;
  duration: number;
  last: boolean;
  hasVideo: boolean;
  videoRef: RefObject<HTMLVideoElement | null>;
  headRef: RefObject<HTMLParagraphElement | null>;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const say = useSay();
  const { num, sec } = useSeconds();
  const meta = useTrackMeta();
  const editable = audio.editable;
  const [local, setLocal] = useState<{ start?: number; volume?: number }>({});
  const pending = useRef<{ start_s?: number; volume?: number }>({});
  const timer = useRef<number>(0);
  const patchRef = useRef(audio.actions.patchLine);
  const lineRef = useRef(line);

  useEffect(() => {
    patchRef.current = audio.actions.patchLine;
    lineRef.current = line;
  });

  // Окно закрыли (или голос убрали), пока правка ждала паузы, — шлём её сразу.
  useEffect(
    () => () => {
      window.clearTimeout(timer.current);
      const body = pending.current;
      pending.current = {};
      if (Object.keys(body).length) void patchRef.current(lineRef.current, body);
    },
    [],
  );

  const send = () => {
    const body = pending.current;
    pending.current = {};
    if (!Object.keys(body).length) return;
    void patchRef.current(lineRef.current, body).then(() => {
      // Ответ пришёл — на экране значение сервера (оно и звучит), если новой правки нет.
      if (!Object.keys(pending.current).length) setLocal({});
    });
  };

  const later = (part: { start_s?: number; volume?: number }) => {
    pending.current = { ...pending.current, ...part };
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(send, PATCH_DEBOUNCE_MS);
  };

  const start = local.start ?? line.start_s;
  const volume = local.volume ?? line.volume;
  const over = lineOverflowS(start, line.duration_s, line.fragment_duration_s ?? duration);
  const ready = line.status === "ready";
  const failed = line.status === "failed";
  const movable = editable && !failed;

  return (
    <div className={SOUND_TRACK}>
      {failed ? (
        <SoundError
          alert={false}
          text={say(trackErrorText(line))}
          busy={audio.deleting === line.id || audio.lineDeleting === line.id}
          onClose={() => void audio.actions.removeLine(line).then(() => headRef.current?.focus({ preventScroll: true }))}
        />
      ) : line.status === "pending" && audio.lineBusy !== line.fragment_key ? (
        <SoundPending>{t("merge.line.pending", { defaultValue: "Голос озвучивается — обычно это несколько секунд." })}</SoundPending>
      ) : null}
      <p className="line-clamp-3 break-words text-sm leading-snug text-foreground">{line.text}</p>
      <p className="text-xs tabular-nums text-muted">
        {[
          t("merge.line.from", { defaultValue: "С {{s}} с", s: num(start) }),
          line.voice_name,
          ready ? meta(line, editable) : "",
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
      {ready && line.url && (
        <audio
          controls
          preload="none"
          src={line.url}
          className="h-10 w-full"
          aria-label={t("merge.line.play", { defaultValue: "Послушать голос сцены" })}
        />
      )}
      {over > 0 && (
        <p className="flex items-start gap-1.5 text-xs leading-snug text-status-wait">
          <FiAlertCircle className="mt-0.5 shrink-0" aria-hidden="true" />
          {last
            ? t("merge.line.overflowEnd", {
                defaultValue: "Голос длиннее, чем осталось ролика: последние {{time}} не прозвучат.",
                time: sec(Math.max(0.1, over)),
              })
            : t("merge.line.overflow", {
                defaultValue: "Голос длиннее, чем осталось фрагмента: последние {{time}} зайдут на следующую сцену.",
                time: sec(Math.max(0.1, over)),
              })}
        </p>
      )}
      {movable && (
        <>
          <StartField
            compact
            value={start}
            duration={line.fragment_duration_s ?? duration}
            onChange={(v) => {
              setLocal((l) => ({ ...l, start: v }));
              later({ start_s: v });
            }}
            onNow={
              hasVideo
                ? () => {
                    const v = clampStart(videoRef.current?.currentTime ?? 0, line.fragment_duration_s ?? duration);
                    setLocal((l) => ({ ...l, start: v }));
                    later({ start_s: v });
                  }
                : undefined
            }
          />
          <VolumeSlider
            label={t("merge.line.volume", { defaultValue: "Громкость" })}
            value={volume}
            max={audio.lineLimits.line_volume_max}
            onChange={(v) => {
              setLocal((l) => ({ ...l, volume: v }));
              later({ volume: Math.round(v * 1000) / 1000 });
            }}
          />
        </>
      )}
      {editable && !failed && line.status !== "pending" && (
        <div className="-ml-2 flex flex-wrap items-center gap-x-1">
          <SoundRemove
            label={t("merge.audio.remove", { defaultValue: "Убрать" })}
            ask={t("merge.line.removeAsk", { defaultValue: "Убрать этот голос? Он оплачен — новый будет стоить заново." })}
            busy={audio.lineDeleting === line.id}
            onRemove={() => void audio.actions.removeLine(line).then(() => headRef.current?.focus({ preventScroll: true }))}
          />
        </div>
      )}
    </div>
  );
}
