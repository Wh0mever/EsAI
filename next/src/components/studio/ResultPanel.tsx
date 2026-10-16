"use client";

import { useEffect, useId, useRef, type CSSProperties } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { FiFilm, FiLoader, FiPlus, FiScissors } from "react-icons/fi";
import SaveMediaButton from "@/components/ui/SaveMediaButton";
import ShareButtons from "@/components/ui/ShareButtons";
import VideoPlayer from "@/components/video/VideoPlayer";
import { VS_BTN_GHOST, VS_CARD, VS_H2, VS_LABEL, VS_SECTION, vx } from "@/components/vstudio/ui/skin";
import { prefersReducedMotion } from "@/components/vstudio/ui/useAutoplayAllowed";
import { addHref } from "@/components/merge/mergeLogic";
import { CS_ANCHOR, CS_GAP, CS_HEAD, CS_NOTE_FAIL } from "./ui/cartoonSkin";
import FilmBlock from "./timeline/FilmBlock";
import type { Project } from "./cartoonTypes";

export type ResultPanelProps = {
  /** Открытый мультфильм: статус, ошибка склейки, готовый ролик, формат. */
  project: Project | null;
  /** Ссылка на страницу мультфильма; пусто — ещё готовится. */
  shareUrl: string;
  readyCount: number;
  assembling: boolean;
  onAssemble: () => void;
  onNewMovie: () => void;
};

/** Кадр не выше этой доли окна: вертикальный мультфильм иначе не помещался бы на экран. */
const MAX_FRAME_VH = 70;

/**
 * Рамка ролика в пропорциях мультфильма: по ширине колонки, но не выше
 * MAX_FRAME_VH — тогда вертикальный встаёт по центру узкой рамкой, а не чёрной
 * полосой во всю ширину. Высота известна до загрузки — страница не прыгает.
 */
function frameStyle(aspect: string): CSSProperties {
  const [w, h] = aspect.split(":").map(Number);
  const ratio = w > 0 && h > 0 ? w / h : 16 / 9;
  return {
    aspectRatio: `${ratio}`,
    width: `min(100%, calc(${MAX_FRAME_VH}vh * ${ratio}))`,
  };
}

/** Печатают в поле — ленту из-под пальцев не уводим. */
function typingNow(): boolean {
  const el = document.activeElement;
  return el instanceof HTMLElement && (el.isContentEditable || el.matches("textarea, input"));
}

/**
 * Готовый мультфильм — карточка в духе результата видеостудии: плеер,
 * «Скачать», «Новый мультфильм» и ссылка, которой можно поделиться. Пока идёт
 * склейка — «проявляющаяся» рамка того же размера, а при пересборке прежний
 * ролик остаётся на месте (его можно смотреть, скачать и отправить) с пометкой
 * «склеиваем». Есть снятые сцены, но склейки ещё не было — подсказка и та же
 * «Собрать мультфильм», что в доке (здесь — тихой кнопкой: золотая на экране
 * одна, в доке).
 *
 * Склейку запускают и из дока внизу, а её ход и результат видны только здесь, в
 * конце ленты: началась склейка или пришёл новый ролик — карточка сама
 * докручивается до экрана (как новый дубль у видеостудии).
 */
export default function ResultPanel({ project, shareUrl, readyCount, assembling, onAssemble, onNewMovie }: ResultPanelProps) {
  const { t } = useTranslation("common");
  const headingId = useId();
  const rootRef = useRef<HTMLElement | null>(null);
  // Склейка — страница сайта: из Mini App в Telegram туда не уводим.
  const inTelegram = (usePathname() ?? "").startsWith("/tg/");
  const projectId = project?.id ?? null;
  const video = project?.result_video ?? "";
  // Что было на прошлом показе: двигаем ленту только на перемену у того же мультфильма.
  const prev = useRef<{ id: number | null; assembling: boolean; video: string } | null>(null);

  useEffect(() => {
    const was = prev.current;
    prev.current = { id: projectId, assembling, video };
    // Первый показ или другой мультфильм — ничего не случилось, ленту не трогаем.
    if (!was || was.id !== projectId || projectId === null) return;
    const started = assembling && !was.assembling;
    const arrived = Boolean(video) && video !== was.video;
    if (!started && !arrived) return;
    // Склейку запустили только что — это ответ на нажатие; ролик же приходит через
    // пару минут, и человек тем временем может печатать в ленте.
    if (!started && typingNow()) return;
    rootRef.current?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "nearest" });
  }, [projectId, assembling, video]);

  if (!project) return null;

  const failed = project.status === "failed" && Boolean(project.error);
  const waiting = !video && !assembling && readyCount > 0;
  if (!video && !assembling && !waiting && !failed) return null;

  const aspect = project.aspect_ratio || "16:9";
  // Постер — кадр первой снятой сцены: ролик начинается с неё.
  const poster = project.scenes.find((s) => s.status === "ready" && s.keyframe)?.keyframe;

  return (
    <section ref={rootRef} aria-labelledby={headingId} className={vx(VS_SECTION, CS_GAP, CS_ANCHOR)}>
      <div className={CS_HEAD}>
        <h2 id={headingId} className={VS_H2}>
          {t("studio_ui.result")}
        </h2>
      </div>

      <div className={vx(VS_CARD, "mt-4 flex flex-col gap-3 p-3 sm:p-4")}>
        {assembling && video ? (
          // Пересборка: прежний ролик остаётся, сверху — что идёт склейка.
          <>
            <p role="status" className="flex items-center gap-2.5 text-sm leading-snug text-muted">
              <FiLoader className="size-4 shrink-0 animate-spin text-vs-accent motion-reduce:animate-none" aria-hidden />
              {t("studio_ui.assembling_note", {
                defaultValue: "Склеиваем мультфильм — это пара минут. Можно не ждать на странице.",
              })}
            </p>
            <div className="mx-auto" style={frameStyle(aspect)}>
              <VideoPlayer
                key={video}
                src={video}
                poster={poster}
                className="h-full w-full"
                playLabel={t("studio_ui.result_play", { defaultValue: "Смотреть мультфильм" })}
              />
            </div>
          </>
        ) : assembling ? (
          <div className="flex flex-col items-center gap-3">
            <FilmBlock className="grid place-items-center rounded-xl text-muted" style={frameStyle(aspect)}>
              <FiLoader className="size-6 animate-spin motion-reduce:animate-none" />
            </FilmBlock>
            <p role="status" className="max-w-md text-center text-sm leading-snug text-muted">
              {t("studio_ui.assembling_note", {
                defaultValue: "Склеиваем мультфильм — это пара минут. Можно не ждать на странице.",
              })}
            </p>
          </div>
        ) : video ? (
          <div className="mx-auto" style={frameStyle(aspect)}>
            <VideoPlayer
              key={video}
              src={video}
              poster={poster}
              className="h-full w-full"
              playLabel={t("studio_ui.result_play", { defaultValue: "Смотреть мультфильм" })}
            />
          </div>
        ) : waiting ? (
          <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="flex items-center gap-2.5 text-sm text-muted">
              <FiFilm className="size-5 shrink-0 text-vs-accent" aria-hidden />
              {t("studio_ui.result_waiting", {
                defaultValue: "Мультфильм соберётся из готовых сцен: {{n}}",
                n: readyCount,
              })}
            </p>
            <button type="button" onClick={() => onAssemble()} className={VS_BTN_GHOST}>
              <FiFilm aria-hidden />
              {t("studio_ui.assemble")}
            </button>
          </div>
        ) : null}

        {failed && (
          <p role="alert" className={CS_NOTE_FAIL}>
            {t("studio_ui.assemble_failed", {
              defaultValue: "Склейка не удалась: {{error}}",
              error: project.error,
            })}
          </p>
        )}

        {video && (
          <>
            <div className="flex flex-wrap gap-2">
              {/* Не <a download>: на iPhone он не скачивает, а открывает файл
                  серой заглушкой «Открыть в iMovie» (жалоба клиента). */}
              <SaveMediaButton
                url={video}
                filename="esai-cartoon.mp4"
                label={t("studio_ui.download_label")}
                className={VS_BTN_GHOST}
              >
                {t("studio_ui.download")}
              </SaveMediaButton>
              <button type="button" onClick={() => onNewMovie()} className={VS_BTN_GHOST}>
                <FiPlus aria-hidden />
                {t("studio_ui.rail_new", { defaultValue: "Новый мультфильм" })}
              </button>
              {/* Склеить мультфильм с другими роликами: склейка откроется уже с ним. Пока он
                  пересобирается, склейка его не примет — ссылку прячем. */}
              {!assembling && !inTelegram && (
                <Link href={addHref([{ type: "cartoon_movie", id: String(project.id) }])} prefetch={false} className={VS_BTN_GHOST}>
                  <FiScissors aria-hidden />
                  {t("studio_ui.result_merge", { defaultValue: "Открыть в склейке" })}
                </Link>
              )}
            </div>

            {/* Поделиться. Ссылка ведёт на страницу мультфильма, а не на
                файл: там ролик играет прямо в мессенджере и стоит призыв
                создать свой — так каждый отправленный мультфильм работает
                рекламой студии. */}
            <div className="flex flex-col gap-1 rounded-xl border border-vs-ink/10 bg-vs-ink/[0.03] p-3.5 sm:p-4">
              <p className={VS_LABEL}>{t("studio_ui.share_title")}</p>
              <p className="mb-2.5 text-xs leading-snug text-muted">{t("studio_ui.share_note")}</p>
              {shareUrl ? (
                <ShareButtons url={shareUrl} text={t("studio_ui.share_text")} />
              ) : (
                <span role="status" className="inline-flex items-center gap-2 text-sm text-muted">
                  <FiLoader className="animate-spin motion-reduce:animate-none" aria-hidden />
                  {t("studio_ui.share_preparing")}
                </span>
              )}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
