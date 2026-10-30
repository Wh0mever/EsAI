"use client";

import { useSyncExternalStore, type CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import { FiAlertCircle, FiClock, FiDownload, FiEdit3, FiLoader, FiMusic, FiPlus } from "react-icons/fi";
import SaveMediaButton, { SAVE_CTA } from "@/components/ui/SaveMediaButton";
import VideoPlayer from "@/components/video/VideoPlayer";
import FilmBlock from "@/components/studio/timeline/FilmBlock";
import { VS_BTN_GHOST, VS_CARD, VS_SUB, vx } from "@/components/vstudio/ui/skin";
import { CS_NOTE_FAIL, CS_NOTE_GOLD } from "@/components/studio/ui/cartoonSkin";
import { hasSound, soundInfo } from "./audioLogic";
import {
  aspectRatio,
  currentFragment,
  downloadName,
  failureText,
  fillText,
  formatDuration,
  isAppleTouch,
  progressShare,
  shortDate,
  type TextSpec,
} from "./mergeLogic";
import type { MergeProject } from "./mergeTypes";
import { useSoundText } from "./soundText";

/**
 * Итог склейки над лентой фрагментов:
 *  - идёт — «плёнка» в пропорциях будущего ролика, что сейчас делается
 *    («Обрабатываю фрагмент 2 из 5», «Склеиваю») и полоска хода;
 *  - готова — плеер, «Скачать», «Новая склейка», до какого числа хранится,
 *    какой звук сведён (он перейдёт в «Изменить и склеить заново» без оплаты);
 *  - не удалась — почему, словами сервера (кредиты не списаны);
 *  - срок хранения вышел — что ролик удалён и его можно склеить снова.
 */

/** Кадр не выше этой доли окна: вертикальный ролик иначе не помещался бы на экран. */
const MAX_FRAME_VH = 62;

function frameStyle(ratio: number): CSSProperties {
  return { aspectRatio: `${ratio}`, width: `min(100%, calc(${MAX_FRAME_VH}vh * ${ratio}))` };
}

const noSubscribe = () => () => {};

/** iPhone или iPad — узнаём уже в браузере; при отрисовке на сервере — нет. */
function useAppleTouch(): boolean {
  return useSyncExternalStore(
    noSubscribe,
    () => isAppleTouch(navigator.userAgent || "", navigator.platform || "", navigator.maxTouchPoints || 0),
    () => false,
  );
}

export type MergeResultProps = {
  project: MergeProject;
  onNew: () => void;
  onCopy: () => void;
};

export default function MergeResult({ project, onNew, onCopy }: MergeResultProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const appleTouch = useAppleTouch();
  const soundText = useSoundText();
  const say = (spec: TextSpec) => (spec.key ? t(spec.key, { defaultValue: spec.ru, ...spec.params }) : fillText(spec.ru, spec.params));
  const ratio = aspectRatio(project.aspect);

  if (project.status === "queued" || project.status === "rendering") {
    const progress = project.progress;
    let stage = t("merge.result.queued", { defaultValue: "В очереди — скоро начнём" });
    if (progress?.stage === "preparing") stage = t("merge.result.preparing", { defaultValue: "Готовлю фрагменты" });
    else if (progress?.stage === "normalizing")
      stage = t("merge.result.normalizing", {
        defaultValue: "Обрабатываю фрагмент {{n}} из {{total}}",
        n: currentFragment(progress),
        total: progress.total,
      });
    else if (progress?.stage === "joining") stage = t("merge.result.joining", { defaultValue: "Склеиваю фрагменты" });
    else if (progress?.stage === "mixing") stage = t("merge.result.mixing", { defaultValue: "Свожу звук" });
    else if (progress?.stage === "saving") stage = t("merge.result.saving", { defaultValue: "Сохраняю ролик" });
    const share = Math.round(progressShare(progress) * 100);
    return (
      <div className={vx(VS_CARD, "flex flex-col items-center gap-3 p-3 sm:p-4")}>
        <FilmBlock className="grid place-items-center rounded-xl text-muted" style={frameStyle(ratio)}>
          <FiLoader className="size-6 animate-spin motion-reduce:animate-none" />
        </FilmBlock>
        <div className="flex w-full max-w-md flex-col items-center gap-2 text-center">
          <p role="status" aria-live="polite" className="text-sm font-medium text-foreground">
            {stage}
          </p>
          <div
            role="progressbar"
            aria-label={t("merge.result.progress", { defaultValue: "Ход склейки" })}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={share}
            className="h-1.5 w-full overflow-hidden rounded-full bg-vs-ink/10"
          >
            <div
              className="h-full rounded-full bg-vs-accent transition-[width] duration-700 motion-reduce:transition-none"
              style={{ width: `${Math.max(3, share)}%` }}
            />
          </div>
          <p className={vx(VS_SUB, "text-[13px]")}>
            {t("merge.result.leave", {
              defaultValue: "Можно закрыть страницу — склейка продолжится, а готовый ролик будет в «Моих склейках».",
            })}
          </p>
        </div>
      </div>
    );
  }

  if (project.status === "ready" && project.result_url) {
    const until = shortDate(project.expires_at);
    const filename = downloadName(project.finished_at);
    const downloadLabel = t("merge.result.download", { defaultValue: "Скачать" });
    const sound = soundInfo(null, project.audio);
    const soundList = hasSound(sound) ? soundText.list(sound) : "";
    return (
      <div className={vx(VS_CARD, "flex flex-col gap-3 p-3 sm:p-4")}>
        <div className="mx-auto" style={frameStyle(ratio)}>
          <VideoPlayer
            key={project.result_url}
            src={project.result_url}
            poster={project.poster_url ?? undefined}
            className="h-full w-full"
            playLabel={t("merge.result.play", { defaultValue: "Смотреть склейку" })}
          />
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted">
          <span className="tabular-nums">
            {formatDuration(project.duration_s ?? project.total_duration_s)} · {project.aspect} ·{" "}
            {t("merge.dock.count", { defaultValue: "{{n}} фрагм.", n: project.fragments })}
          </span>
          {until && (
            <span className="inline-flex items-center gap-1.5">
              <FiClock className="size-3.5 shrink-0" aria-hidden="true" />
              {t("merge.until", { defaultValue: "Хранится до {{date}}", date: until })}
            </span>
          )}
          {soundList && (
            <span className="inline-flex items-center gap-1.5">
              <FiMusic className="size-3.5 shrink-0" aria-hidden="true" />
              {t("merge.result.sound", { defaultValue: "Звук: {{list}}", list: soundList })}
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {appleTouch ? (
            // На iPhone <a download> не скачивает, а открывает ролик серой заглушкой
            // «Открыть в iMovie» (жалоба клиента) — сохраняем системным окном, как студии.
            <SaveMediaButton
              url={project.result_url}
              filename={filename}
              label={downloadLabel}
              className={SAVE_CTA}
            >
              {downloadLabel}
            </SaveMediaButton>
          ) : (
            // Сам файл из /media/ — его отдаёт nginx: ролик в сотню мегабайт не держит
            // поток API (их на весь сайт 24) и не ложится целиком в память вкладки.
            <a href={project.result_url} download={filename} className={SAVE_CTA}>
              <FiDownload aria-hidden="true" />
              {downloadLabel}
            </a>
          )}
          <button type="button" onClick={onNew} className={VS_BTN_GHOST}>
            <FiPlus aria-hidden="true" />
            {t("merge.new", { defaultValue: "Новая склейка" })}
          </button>
          <button type="button" onClick={onCopy} className={VS_BTN_GHOST}>
            <FiEdit3 aria-hidden="true" />
            {t("merge.result.copy", { defaultValue: "Изменить и склеить заново" })}
          </button>
        </div>
        {(sound.voice || sound.music) && (
          <p className="text-[13px] leading-snug text-muted">
            {t("merge.result.copySound", {
              defaultValue: "«Изменить и склеить заново» возьмёт и звук — платить за голос и музыку ещё раз не нужно.",
            })}
          </p>
        )}
      </div>
    );
  }

  if (project.status === "failed") {
    return (
      <div role="alert" className={vx(CS_NOTE_FAIL, "flex items-start gap-2.5")}>
        <FiAlertCircle className="mt-0.5 shrink-0" aria-hidden="true" />
        <p className="min-w-0 flex-1">{say(failureText(project.error_code, project.error_fragment, project.error))}</p>
      </div>
    );
  }

  if (project.status === "expired") {
    return (
      <div role="status" className={vx(CS_NOTE_GOLD, "flex items-start gap-2.5")}>
        <FiClock className="mt-0.5 shrink-0 text-vs-accent" aria-hidden="true" />
        <p className="min-w-0 flex-1">
          {project.price_credits === 0
            ? t("merge.result.expired_free", {
                defaultValue: "Срок хранения вышел, и ролик удалён. Его можно склеить снова.",
              })
            : t("merge.result.expired", {
                defaultValue: "Срок хранения вышел, и ролик удалён. Его можно склеить снова — кредиты спишутся ещё раз.",
              })}
        </p>
      </div>
    );
  }

  return null;
}
