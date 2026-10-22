"use client";

import type { KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { FiFilm, FiPlus, FiRefreshCw, FiX } from "react-icons/fi";
import { VS_BTN_GHOST, VS_FOCUS, VS_ICON_BTN, VS_SEG_THUMB, VS_SEG_TRACK, VS_SUB, vx } from "@/components/vstudio/ui/skin";
import { CS_EMPTY, CS_NOTE_GOLD, CS_SKELETON } from "@/components/studio/ui/cartoonSkin";
import { CLIP_SOUNDS } from "./audioLogic";
import { refusalText, type LocalItem } from "./mergeLogic";
import type { MergeClipSound } from "./mergeTypes";
import SoundMusic from "./SoundMusic";
import SoundVoice from "./SoundVoice";
import { SoundBlock, SoundError, useSay } from "./soundUi";
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
};

export default function MergeSoundPanel({ audio, items, price, variant, headingId, onClose, onAdd }: MergeSoundPanelProps) {
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
        <SoundMusic audio={audio} items={items} />
        <ClipBlock audio={audio} />
        <p className="px-1 text-xs leading-snug text-muted-2">
          {t("merge.audio.money", {
            defaultValue:
              "Голос и музыка оплачиваются один раз — когда готовы; не получится — кредиты не спишутся. «Склеить» стоит {{price}}: звук второй раз не списывается.",
            price: priceText,
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
