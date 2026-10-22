"use client";

import { useId, useRef } from "react";
import { useTranslation } from "react-i18next";
import { FiLoader, FiMusic, FiRefreshCw, FiUpload, FiX } from "react-icons/fi";
import { VS_BTN_GHOST, VS_BTN_LINK, VS_LABEL, vx } from "@/components/vstudio/ui/skin";
import { mergeTotal, musicRefusal, textChars, trackErrorText } from "./audioLogic";
import { formatDuration, type LocalItem } from "./mergeLogic";
import {
  SOUND_PAID_BTN,
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
import { uploadShare } from "./uploadLogic";
import type { MergeAudioModel } from "./useMergeAudio";

/** Короче склейки больше чем на секунду — трек повторится по кругу: говорим об этом заранее. */
const LOOP_SLACK_S = 1;

/**
 * «Музыка»: по описанию на всю длину склейки («Создать · N кр», цена — за
 * нынешнюю длину) или свой трек бесплатно. Под голосом музыка сама тише —
 * это делает сведение. Готовая — плеер, громкость, «Заменить», «Убрать».
 */
export default function SoundMusic({ audio, items }: { audio: MergeAudioModel; items: readonly LocalItem[] }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const say = useSay();
  const meta = useTrackMeta();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const promptId = useId();
  const countId = useId();
  const hintId = useId();
  const progressId = useId();

  const { music, draft, editable, configured, limits } = audio;
  const busy = audio.musicBusy;
  // Места музыки на сайте только что были заняты (music_busy): «Создать» ждёт минуту — как сказано
  // в отказе сервера («попробуйте через минуту»), под кнопкой — тот же совет с отсчётом.
  const wait = audio.musicWait;
  const upload = audio.upload;
  const ready = music.ready;
  const replacing = Boolean(ready) && audio.forms.music;
  const showForm = editable && !music.pending && (!ready || audio.forms.music);
  const quote = audio.musicQuote;
  const total = mergeTotal(items);
  const credits = (n: number) => t("top.balance", { defaultValue: "{{n}} кр", n });
  const chars = textChars(draft.prompt);
  const over = chars > limits.prompt_chars;
  const refusal = musicRefusal(draft.prompt, quote?.seconds ?? 0, limits);
  const loops = Boolean(ready && typeof ready.duration_s === "number" && ready.duration_s + LOOP_SLACK_S < total);

  const run = () => {
    // Свой трек ещё идёт — новая музыка столкнулась бы с ним на сервере (audio_busy).
    if (busy || upload || wait > 0) return;
    if (refusal) {
      promptRef.current?.focus();
      return;
    }
    audio.actions.makeMusic();
  };

  const chip =
    busy || music.pending || upload ? (
      <SoundChip tone="busy">{t("merge.audio.chipMaking", { defaultValue: "Делается…" })}</SoundChip>
    ) : ready ? (
      <SoundChip tone="ready">{t("merge.audio.chipReady", { defaultValue: "Готово" })}</SoundChip>
    ) : null;

  const hint =
    wait > 0
      ? t("merge.audio.music.busyWait", {
          defaultValue: "Сейчас готовится много музыки — попробуйте через {{n}} с.",
          n: wait,
        })
      : refusal
        ? say(refusal)
        : quote
          ? t("merge.audio.music.runHint", {
              defaultValue: "Музыка на {{time}} — под длину склейки.",
              time: formatDuration(quote.seconds),
            })
          : "";

  const uploadStatus = upload
    ? upload.phase === "processing"
      ? t("merge.audio.music.processing", { defaultValue: "Проверяю трек — это несколько секунд…" })
      : t("merge.upload.sending", { defaultValue: "Загружаю… {{pct}} %", pct: upload.pct })
    : "";

  return (
    <SoundBlock
      icon={FiMusic}
      title={t("merge.audio.music.title", { defaultValue: "Музыка" })}
      chip={chip}
      headingRef={headingRef}
      sub={t("merge.audio.music.sub", {
        defaultValue: "Играет всю склейку — {{time}}. Под голосом сама становится тише.",
        time: formatDuration(total),
      })}
    >
      {audio.errors.music && (
        <SoundError
          text={say(audio.errors.music)}
          onClose={() => {
            audio.actions.dismissError("music");
            // Неудачная попытка осталась на сервере плашкой — скрываем её вместе с отказом, одним нажатием.
            if (music.failed) void audio.actions.removeTrack(music.failed);
            keepFocus(headingRef);
          }}
        />
      )}
      {/* Отказ на нажатие уже сказал то же самое — вторая плашка про ту же дорожку не нужна. */}
      {music.failed && !busy && !audio.errors.music && (
        <SoundError
          alert={false}
          text={say(trackErrorText(music.failed))}
          busy={audio.deleting === music.failed.id}
          onClose={() => {
            const failed = music.failed;
            if (failed) void audio.actions.removeTrack(failed).then(() => keepFocus(headingRef));
          }}
        />
      )}
      {music.pending && (
        <SoundPending>
          {t("merge.audio.music.pending", {
            defaultValue: "Музыка создаётся — обычно около минуты на минуту музыки. «Склеить» подождёт её.",
          })}
        </SoundPending>
      )}

      {ready && (
        <div className={SOUND_TRACK}>
          <p className="line-clamp-3 break-words text-sm leading-snug text-foreground">
            {ready.source === "upload"
              ? ready.title || t("merge.audio.ownTrack", { defaultValue: "Свой трек" })
              : ready.prompt}
          </p>
          <p className="text-xs tabular-nums text-muted">
            {[
              ready.source === "upload"
                ? t("merge.audio.ownTrack", { defaultValue: "Свой трек" })
                : t("merge.audio.music.generated", { defaultValue: "По описанию" }),
              meta(ready, editable),
            ].join(" · ")}
          </p>
          <audio
            controls
            preload="none"
            src={ready.url ?? undefined}
            className="h-10 w-full"
            aria-label={t("merge.audio.music.play", { defaultValue: "Послушать музыку" })}
          />
          {loops && (
            <p className="text-xs leading-snug text-muted">
              {t("merge.audio.music.loop", { defaultValue: "Музыка короче склейки — она повторится по кругу." })}
            </p>
          )}
          {editable && !replacing && (
            <>
              <VolumeSlider
                label={t("merge.audio.music.volume", { defaultValue: "Громкость музыки" })}
                value={audio.musicVolume}
                max={limits.music_volume_max}
                onChange={audio.actions.setMusicVolume}
              />
              <div className="-ml-2 flex flex-wrap items-center gap-x-1">
                <button type="button" onClick={() => audio.actions.openForm("music", ready)} className={VS_BTN_LINK}>
                  <FiRefreshCw aria-hidden="true" />
                  {t("merge.audio.replace", { defaultValue: "Заменить" })}
                </button>
                <SoundRemove
                  label={t("merge.audio.remove", { defaultValue: "Убрать" })}
                  ask={
                    ready.source === "upload"
                      ? null
                      : t("merge.audio.music.removeAsk", {
                          defaultValue: "Убрать музыку? Она оплачена — новая будет стоить заново.",
                        })
                  }
                  busy={audio.deleting === ready.id}
                  onRemove={() => void audio.actions.removeTrack(ready).then(() => keepFocus(headingRef))}
                />
              </div>
            </>
          )}
        </div>
      )}

      {showForm && (
        <div className="flex flex-col gap-3">
          {/* «Убрать» спрашивает про оплату — замена (и своим треком) удаляет оплаченную музыку так же. */}
          {replacing && ready?.source === "generated" && (
            <p className="text-xs leading-snug text-muted">
              {t("merge.audio.music.replaceNote", {
                defaultValue: "Новая музыка или свой трек заменят прежнюю. Она оплачена — кредиты за неё не вернутся.",
              })}
            </p>
          )}
          {configured ? (
            <>
              <div className="flex flex-col gap-1.5">
                <label htmlFor={promptId} className={VS_LABEL}>
                  {t("merge.audio.music.prompt", { defaultValue: "Опишите музыку" })}
                </label>
                <textarea
                  ref={promptRef}
                  id={promptId}
                  rows={2}
                  value={draft.prompt}
                  onChange={(e) => audio.actions.setPrompt(e.currentTarget.value)}
                  placeholder={t("merge.audio.music.placeholder", {
                    defaultValue: "Например: спокойное пианино, лёгкий джаз или бодрый поп без слов",
                  })}
                  aria-describedby={countId}
                  aria-invalid={over || undefined}
                  className={SOUND_TEXT_FIELD}
                />
                <p id={countId} className={vx("text-xs tabular-nums", over ? "text-status-fail" : "text-muted-2")}>
                  {t("merge.audio.chars", { defaultValue: "{{n}} из {{max}} символов", n: chars, max: limits.prompt_chars })}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={run}
                  aria-disabled={busy || Boolean(refusal) || upload !== null || wait > 0 || undefined}
                  aria-busy={busy || undefined}
                  aria-describedby={hint ? hintId : undefined}
                  className={vx(SOUND_PAID_BTN, busy && "!cursor-wait")}
                >
                  {busy ? <FiLoader className={SOUND_SPIN} aria-hidden="true" /> : <FiMusic aria-hidden="true" />}
                  {busy
                    ? t("merge.audio.music.running", { defaultValue: "Заказываю…" })
                    : t("merge.audio.music.run", {
                        defaultValue: "Создать · {{price}}",
                        price: credits(quote?.credits ?? 0),
                      })}
                </button>
                {replacing && !busy && (
                  <button type="button" onClick={() => audio.actions.closeForm("music")} className={VS_BTN_GHOST}>
                    {t("nav.cancel", { defaultValue: "Отмена" })}
                  </button>
                )}
              </div>
              {hint && (
                <p id={hintId} className="-mt-1 text-xs leading-snug text-muted">
                  {hint}
                </p>
              )}
              <div className="flex items-center gap-3 text-xs text-muted-2" aria-hidden="true">
                <span className="h-px flex-1 bg-vs-ink/10" />
                {t("merge.audio.music.or", { defaultValue: "или" })}
                <span className="h-px flex-1 bg-vs-ink/10" />
              </div>
            </>
          ) : (
            <p className="text-[13px] leading-snug text-muted">
              {t("merge.audio.music.off", { defaultValue: "Музыка по описанию пока не подключена — загрузите свой трек." })}
            </p>
          )}

          {upload ? (
            <div className="flex flex-col gap-2 rounded-xl border border-dashed border-vs-ink/15 p-3">
              <div className="flex min-w-0 items-center gap-2">
                <p id={progressId} className="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground" title={upload.name}>
                  {upload.name}
                </p>
                {upload.phase === "upload" && (
                  <button type="button" onClick={audio.actions.cancelUpload} className={vx(VS_BTN_LINK, "shrink-0 !px-2")}>
                    <FiX aria-hidden="true" />
                    {t("merge.upload.cancel", { defaultValue: "Отменить" })}
                  </button>
                )}
              </div>
              <div
                role="progressbar"
                aria-labelledby={progressId}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(uploadShare(upload.pct, upload.phase) * 100)}
                aria-valuetext={uploadStatus}
                className="h-1.5 w-full overflow-hidden rounded-full bg-vs-ink/10"
              >
                <div
                  className="h-full rounded-full bg-vs-accent transition-[width] duration-300 motion-reduce:transition-none"
                  style={{ width: `${uploadShare(upload.pct, upload.phase) * 100}%` }}
                />
              </div>
              <p className="flex items-center gap-1.5 text-xs tabular-nums text-muted" aria-hidden="true">
                {upload.phase === "processing" && <FiLoader className={vx("shrink-0", SOUND_SPIN)} />}
                {uploadStatus}
              </p>
            </div>
          ) : (
            <div className="flex flex-col items-start gap-1.5">
              <button
                type="button"
                onClick={() => {
                  if (!busy) fileRef.current?.click();
                }}
                aria-disabled={busy || undefined}
                className={vx(VS_BTN_GHOST, busy && "!cursor-not-allowed opacity-60")}
              >
                <FiUpload className="text-vs-accent" aria-hidden="true" />
                {t("merge.audio.music.upload", { defaultValue: "Загрузить свой трек" })}
              </button>
              <p className="text-xs leading-snug text-muted-2">
                {t("merge.audio.music.uploadHint", {
                  defaultValue: "Бесплатно · MP3, M4A, WAV, OGG, FLAC и другие · до {{mb}} МБ · до {{min}} мин",
                  mb: limits.upload_max_mb,
                  min: Math.round(limits.upload_max_s / 60),
                })}
              </p>
              {replacing && !configured && (
                <button type="button" onClick={() => audio.actions.closeForm("music")} className={VS_BTN_GHOST}>
                  {t("nav.cancel", { defaultValue: "Отмена" })}
                </button>
              )}
            </div>
          )}
          <input
            ref={fileRef}
            type="file"
            accept={limits.accept}
            tabIndex={-1}
            aria-hidden="true"
            className="sr-only"
            onChange={(e) => {
              const file = e.currentTarget.files?.[0];
              // Тот же файл ещё раз (после отказа) — снова событие change.
              e.currentTarget.value = "";
              if (file) audio.actions.uploadMusic(file);
            }}
          />
        </div>
      )}
    </SoundBlock>
  );
}
