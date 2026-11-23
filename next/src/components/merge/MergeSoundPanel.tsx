"use client";

import type { KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { FiAlertCircle, FiFilm, FiMessageCircle, FiMic, FiPlus, FiRefreshCw, FiX } from "react-icons/fi";
import { VS_BTN_GHOST, VS_BTN_LINK, VS_FOCUS, VS_ICON_BTN, VS_SEG_THUMB, VS_SEG_TRACK, VS_SUB, vx } from "@/components/vstudio/ui/skin";
import { CS_EMPTY, CS_NOTE_GOLD, CS_SKELETON } from "@/components/studio/ui/cartoonSkin";
import { CLIP_SOUNDS, linesOf, orphanLines } from "./audioLogic";
import { refusalText, type LocalItem } from "./mergeLogic";
import type { MergeClipSound } from "./mergeTypes";
import SoundMusic from "./SoundMusic";
import SoundVoice from "./SoundVoice";
import { SOUND_TRACK, SoundBlock, SoundChip, SoundError, SoundRemove, useSay, useSeconds } from "./soundUi";
import { useSoundText } from "./soundText";
import type { MergeAudioModel } from "./useMergeAudio";

/**
 * Панель «Звук» склейки: голос за кадром, музыка и звук роликов. Всё
 * сводится при «Склеить»; голос и музыка оплачиваются один раз — когда
 * готовы, — и «Склеить» их второй раз не списывает.
 *
 * С 1024 px панель встаёт в левую колонку вместо выбора роликов (лента
 * остаётся на виду — видно, с какого фрагмента голос); уже — нижняя шторка.
 */

export type MergeSoundPanelProps = {
  audio: MergeAudioModel;
  items: readonly LocalItem[];
  /** Цена склейки — для строки «Склеить стоит N кр, звук второй раз не списывается». */
  price: number;
  /** column — колонка слева (заголовок и ✕ свои), sheet — внутри шторки с заголовком. */
  variant: "column" | "sheet";
  headingId: string;
  onClose: () => void;
  /** Фрагментов нет — к выбору роликов. */
  onAdd: () => void;
  /** Открыть окно голоса сцены фрагмента (номер с нуля). */
  onVoice?: (index: number) => void;
};

export default function MergeSoundPanel({ audio, items, price, variant, headingId, onClose, onAdd, onVoice }: MergeSoundPanelProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const say = useSay();
  const column = variant === "column";
  const title = t("merge.audio.title", { defaultValue: "Звук" });
  const sub = t("merge.audio.sub", { defaultValue: "Голос за кадром, музыка и звук роликов" });
  const closeLabel = t("merge.audio.close", { defaultValue: "Закрыть «Звук» и вернуться к видео" });

  // В колонке Esc закрывает панель (в шторке это делает сама шторка).
  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (!column || e.key !== "Escape" || e.defaultPrevented) return;
    if (e.target instanceof HTMLSelectElement) return;
    e.preventDefault();
    onClose();
  };

  const priceText = price > 0 ? t("top.balance", { defaultValue: "{{n}} кр", n: price }) : t("merge.dock.free", { defaultValue: "бесплатно" });
  const block = audio.state?.edit_block;

  let body;
  if (items.length === 0) {
    body = (
      <div className={CS_EMPTY}>
        <p>
          {t("merge.audio.empty", {
            defaultValue: "Сначала добавьте фрагменты: голос и музыка подбираются под склейку.",
          })}
        </p>
        <button type="button" onClick={onAdd} className={VS_BTN_GHOST}>
          <FiPlus aria-hidden="true" />
          {t("merge.tl.add", { defaultValue: "Добавить видео" })}
        </button>
      </div>
    );
  } else if (!audio.available || audio.loading) {
    body = (
      <div className="flex flex-col gap-3" aria-busy="true">
        <span className="sr-only">{t("merge.audio.loading", { defaultValue: "Загружаю звук…" })}</span>
        {[0, 1, 2].map((i) => (
          <div key={i} className={vx("h-32 animate-pulse rounded-2xl motion-reduce:animate-none", CS_SKELETON)} aria-hidden="true" />
        ))}
      </div>
    );
  } else if (audio.loadFailed) {
    body = (
      <div className={CS_EMPTY}>
        <p>{t("merge.audio.loadFailed", { defaultValue: "Не удалось загрузить звук склейки." })}</p>
        <button type="button" onClick={audio.actions.reload} className={VS_BTN_GHOST}>
          <FiRefreshCw aria-hidden="true" />
          {t("page.retry", { defaultValue: "Попробовать снова" })}
        </button>
      </div>
    );
  } else {
    body = (
      <>
        {!audio.editable && block && (
          <p role="status" className={vx(CS_NOTE_GOLD, "!px-3 !py-2.5 !text-[13px] leading-snug")}>
            {say(refusalText(block.error_code, {}, block.error))}
          </p>
        )}
        {audio.errors.settings && (
          <SoundError text={say(audio.errors.settings)} onClose={() => audio.actions.dismissError("settings")} />
        )}
        {audio.editable && !audio.configured && (
          <p className={vx(CS_NOTE_GOLD, "!px-3 !py-2.5 !text-[13px] leading-snug")}>{say(refusalText("audio_not_configured"))}</p>
        )}
        <SoundVoice audio={audio} items={items} />
        <SceneLinesBlock audio={audio} items={items} onVoice={onVoice} />
        <SoundMusic audio={audio} items={items} />
        <ClipBlock audio={audio} />
        <p className="px-1 text-xs leading-snug text-muted-2">
          {price > 0
            ? t("merge.audio.money", {
                defaultValue:
                  "Голос и музыка оплачиваются один раз — когда готовы; не получится — кредиты не спишутся. «Склеить» стоит {{price}}: звук второй раз не списывается.",
                price: priceText,
              })
            : t("merge.audio.money_free", {
                defaultValue:
                  "Голос и музыка оплачиваются один раз — когда готовы; не получится — кредиты не спишутся. Сама склейка сейчас бесплатная, и звук второй раз не списывается.",
              })}
        </p>
      </>
    );
  }

  return (
    <section
      aria-labelledby={column ? headingId : undefined}
      aria-label={column ? undefined : title}
      onKeyDown={onKeyDown}
      className="flex min-w-0 flex-col gap-3"
    >
      {column ? (
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 id={headingId} tabIndex={-1} className="text-base font-semibold text-foreground focus:outline-none">
              {title}
            </h2>
            <p className={vx(VS_SUB, "mt-0.5 text-[13px]")}>{sub}</p>
          </div>
          <button type="button" onClick={onClose} className={vx(VS_ICON_BTN, "md:!size-9")} aria-label={closeLabel} title={closeLabel}>
            <FiX className="size-4" aria-hidden="true" />
          </button>
        </div>
      ) : (
        <p className={vx(VS_SUB, "text-[13px]")}>{sub}</p>
      )}
      {body}
    </section>
  );
}

/** «Звук роликов»: оставить, тише или выключить — бесплатно, сохраняется сразу. */
function ClipBlock({ audio }: { audio: MergeAudioModel }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const sound = useSoundText();
  const hint = (c: MergeClipSound) => {
    if (c === "quiet") return t("merge.audio.clipHint.quiet", { defaultValue: "Звук роликов тише в три раза — голос и музыку слышно лучше." });
    if (c === "off") return t("merge.audio.clipHint.off", { defaultValue: "Без звука роликов — только голос и музыка." });
    return t("merge.audio.clipHint.keep", { defaultValue: "Звук роликов — как есть." });
  };
  const clips = audio.limits.clip_sounds.length ? audio.limits.clip_sounds : CLIP_SOUNDS;
  return (
    <SoundBlock icon={FiFilm} title={t("merge.audio.clip.title", { defaultValue: "Звук роликов" })}>
      <div
        role="group"
        aria-label={t("merge.audio.clip.title", { defaultValue: "Звук роликов" })}
        className={vx("grid grid-cols-3 gap-1 rounded-full p-1", VS_SEG_TRACK)}
      >
        {clips.map((c) => {
          const on = audio.clip === c;
          return (
            <button
              key={c}
              type="button"
              aria-pressed={on}
              aria-disabled={!audio.editable || undefined}
              onClick={() => {
                if (audio.editable && !on) audio.actions.setClipSound(c);
              }}
              className={vx(
                "inline-flex min-h-11 min-w-0 cursor-pointer items-center justify-center rounded-full px-2 text-[13px] font-medium transition-colors aria-disabled:cursor-not-allowed md:min-h-9",
                VS_FOCUS,
                on ? vx(VS_SEG_THUMB, "text-vs-accent") : "text-muted hover:text-foreground",
              )}
            >
              <span className="truncate">{sound.clip(c)}</span>
            </button>
          );
        })}
      </div>
      <p className="text-xs leading-snug text-muted">{hint(audio.clip)}</p>
    </SoundBlock>
  );
}

/**
 * «Голоса сцен»: свой текст на конкретный фрагмент с нужной секунды (окно «Голос» у фрагмента
 * в ленте). Здесь — какие фрагменты уже озвучены и голоса, чей ролик убрали из склейки: в
 * склейку они не идут, их можно убрать (или вернуть ролик).
 */
function SceneLinesBlock({
  audio,
  items,
  onVoice,
}: {
  audio: MergeAudioModel;
  items: readonly LocalItem[];
  onVoice?: (index: number) => void;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const say = useSay();
  const { sec } = useSeconds();
  const orphans = orphanLines(audio.lines);
  const voiced = items
    .map((it, index) => ({ it, index, lines: linesOf(audio.lines, it.key).filter((l) => l.status !== "failed") }))
    .filter((x) => x.lines.length > 0);
  const total = voiced.reduce((n, x) => n + x.lines.length, 0);
  const untitled = t("merge.untitled", { defaultValue: "Без названия" });
  return (
    <SoundBlock
      icon={FiMessageCircle}
      title={t("merge.line.blockTitle", { defaultValue: "Голоса сцен" })}
      chip={total > 0 ? <SoundChip tone="ready">{t("merge.line.added", { defaultValue: "Добавлено: {{n}}", n: total })}</SoundChip> : null}
      sub={t("merge.line.blockSub", {
        defaultValue: "Свой текст на конкретный фрагмент — с нужной секунды. Нажмите «Голос» у фрагмента в ленте.",
      })}
    >
      {voiced.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {voiced.map(({ it, index, lines }) => (
            <li key={it.key} className="flex min-w-0 items-center justify-between gap-2 text-[13px]">
              <span className="min-w-0 truncate text-foreground">
                {t("merge.line.row", {
                  defaultValue: "№{{n}} · {{title}} — с {{times}}",
                  n: index + 1,
                  title: it.title.trim() || untitled,
                  // «; » между секундами: запятая — уже десятичный знак («2,5 с; 4,0 с»).
                  times: lines.map((l) => sec(l.start_s)).join("; "),
                })}
              </span>
              {onVoice && audio.editable && (
                <button
                  type="button"
                  onClick={() => onVoice(index)}
                  className={vx(VS_BTN_LINK, "shrink-0")}
                  // В имени — видимое слово «Открыть» (голосовое управление: «нажми Открыть»).
                  aria-label={t("merge.line.openRow", { defaultValue: "Открыть голос сцены, фрагмент {{n}}", n: index + 1 })}
                >
                  <FiMic aria-hidden="true" />
                  {t("merge.line.edit", { defaultValue: "Открыть" })}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {orphans.map((line) => (
        <div key={line.id} className={SOUND_TRACK}>
          <p className="flex items-start gap-1.5 text-[13px] leading-snug text-status-wait">
            <FiAlertCircle className="mt-0.5 shrink-0" aria-hidden="true" />
            {say(refusalText("line_orphan"))}
          </p>
          <p className="line-clamp-2 break-words text-sm leading-snug text-foreground">{line.text}</p>
          {audio.editable && line.status !== "pending" && (
            <div className="-ml-2">
              <SoundRemove
                label={t("merge.audio.remove", { defaultValue: "Убрать" })}
                ask={
                  line.status === "ready"
                    ? t("merge.line.removeAsk", { defaultValue: "Убрать этот голос? Он оплачен — новый будет стоить заново." })
                    : null
                }
                busy={audio.lineDeleting === line.id}
                onRemove={() => void audio.actions.removeLine(line)}
              />
            </div>
          )}
        </div>
      ))}
    </SoundBlock>
  );
}
