"use client";

import { useEffect, useEffectEvent, useId, useRef, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { FiAlertTriangle, FiFilm, FiLoader, FiPause, FiPlay, FiVolume2, FiVolumeX } from "react-icons/fi";
import LazyClip, { CLIP_BLANK } from "@/components/vstudio/ui/LazyClip";
import {
  PLAY_BLOCKED,
  PLAY_ON,
  markAutoplayBlocked,
  playState,
  releaseAuto,
  releasePlay,
  requestPlay,
  requestSolo,
  subscribePlay,
} from "@/components/vstudio/ui/playBudget";
import { VS_FOCUS, VS_ON_MEDIA, vx } from "@/components/vstudio/ui/skin";
import { useAutoplayAllowed } from "@/components/vstudio/ui/useAutoplayAllowed";
import { LiveFrame } from "../library/SceneCard";
import type { StudioScene } from "../SceneTimeline";

type Frame = "video" | "preview" | "concept" | "hero" | "image" | "blank";

/** С этой доли кадра на экране снятая сцена заводится сама (как STAGE_SHARE у LazyClip). */
const SHARE = 0.5;

/** Круглая кнопка запуска поверх кадра — как у LazyClip: кадр тёмный в любой теме. */
const PLAY_GLYPH = "grid size-11 place-items-center rounded-full bg-black/60 text-white transition-transform duration-200 hover:scale-110 motion-reduce:transition-none";
/** Пауза и звук в углу кадра: кружок 32 px, зона нажатия 44 px. */
const MEDIA_BTN = vx("grid size-11 cursor-pointer place-items-center rounded-full", VS_FOCUS);
const MEDIA_GLYPH = "grid size-8 place-items-center rounded-full bg-black/60 text-white transition-colors hover:bg-black/75";

const idle = () => 0;

/**
 * Снятая сцена в ленте: играет сама, без звука и по кругу (клиент: лента сразу
 * показывает героя, сцену и движение), но только пока карточка на экране и
 * устройство не просит «меньше движения» или экономии трафика. До первого
 * появления на экране ролик не грузится вовсе — в длинной ленте их десятки.
 *
 * Сколько роликов играет разом, решает общий бюджет вкладки (playBudget), как у
 * витрины: в сетке ленты на широком экране их бывает десяток. Системной панели
 * плеера нет (globals.css прячет её в Chrome и Safari), поэтому свои кнопки:
 * пауза и звук в углу, запуск — по центру или нажатием на кадр. Паузу и звук,
 * выбранные человеком, уважаем: сами такой ролик больше не заводим.
 */
function ReadyVideo({ src, poster, label }: { src: string; poster: string; label: string }) {
  const { t } = useTranslation("common");
  const { t: tv } = useTranslation("vstudio", { useSuspense: false });
  const id = useId();
  const ref = useRef<HTMLVideoElement | null>(null);
  const allowed = useAutoplayAllowed();
  const budget = useSyncExternalStore(subscribePlay, () => playState(id), idle);
  const granted = (budget & PLAY_ON) !== 0;
  const blocked = (budget & PLAY_BLOCKED) !== 0;
  // Хоть раз был на экране (тогда и грузим), виден сейчас хоть краем, виден наполовину.
  const [seen, setSeen] = useState(() => typeof IntersectionObserver === "undefined");
  const [visible, setVisible] = useState(() => typeof IntersectionObserver === "undefined");
  const [inView, setInView] = useState(() => typeof IntersectionObserver === "undefined");
  const [paused, setPaused] = useState(true);
  const [muted, setMuted] = useState(true);
  // Паузу поставил человек — дальше ролик заводит только он сам.
  const [held, setHeld] = useState(false);
  // Паузу поставили мы (карточка ушла с экрана, место отдали другому) — это не выбор человека.
  const ours = useRef(false);

  // Сам — только без звука: звук включил человек, и заводить его сами мы не вправе.
  const auto = inView && allowed && !blocked && !held && muted;

  const start = useEffectEvent((video: HTMLVideoElement) => {
    video.play()?.catch((err: unknown) => {
      if (err instanceof DOMException && err.name === "NotAllowedError") {
        markAutoplayBlocked();
        releasePlay(id);
      }
    });
  });

  const onSight = useEffectEvent((entry: IntersectionObserverEntry) => {
    if (entry.isIntersecting) setSeen(true);
    setVisible(entry.isIntersecting);
    setInView(entry.isIntersecting && entry.intersectionRatio >= SHARE);
  });

  useEffect(() => {
    const video = ref.current;
    if (!video || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        const last = entries[entries.length - 1];
        if (last) onSight(last);
      },
      { threshold: [0, SHARE] },
    );
    io.observe(video);
    return () => io.disconnect();
  }, []);

  // Совсем ушёл с экрана — останавливаем и запущенный нажатием; виден — просим место.
  useEffect(() => {
    if (!visible) releasePlay(id);
    else if (auto) requestPlay(id);
    else releaseAuto(id);
  }, [id, visible, auto]);

  useEffect(() => () => releasePlay(id), [id]);

  // Место дали — заводим; забрали — останавливаем.
  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    if (granted && video.paused) start(video);
    else if (!granted && !video.paused) {
      ours.current = true;
      video.pause();
    }
  }, [granted]);

  /** Запуск нажатием: play() — прямо в обработчике, иначе iOS сочтёт его автозапуском. */
  const play = () => {
    const video = ref.current;
    if (!video) return;
    requestSolo(id);
    video.play()?.catch(() => releasePlay(id));
  };
  const pause = () => {
    const video = ref.current;
    if (video && !video.paused) video.pause();
  };
  const toggleSound = () => {
    const video = ref.current;
    if (!video) return;
    video.muted = !video.muted;
    setMuted(video.muted);
    // Звук включили — это уже выбор человека: ролик держит место и играет.
    if (!video.muted) play();
  };

  const playLabel = tv("run.actions.play", { defaultValue: "Смотреть" });
  const pauseLabel = t("studio_ui.tl_pause", { defaultValue: "Пауза" });
  const soundLabel = muted
    ? t("studio_ui.tl_sound_on", { defaultValue: "Включить звук" })
    : t("studio_ui.tl_sound_off", { defaultValue: "Выключить звук" });
  // Кнопка запуска — когда сам ролик сейчас не пойдёт; иначе она мигала бы перед стартом.
  const needsTap = paused && !(auto && granted);

  return (
    <>
      {/* Нажатие на кадр — пауза или запуск, как в плеере; с клавиатуры — кнопки ниже. */}
      <video
        ref={ref}
        src={src}
        muted
        loop
        playsInline
        preload={seen ? "metadata" : "none"}
        // Обложку — тоже с первого появления на экране: атрибут poster браузер грузит сразу.
        poster={(seen && poster) || undefined}
        aria-label={label}
        onClick={() => (paused ? play() : pause())}
        onPlay={() => {
          setPaused(false);
          setHeld(false);
        }}
        onPause={() => {
          setPaused(true);
          if (ours.current) ours.current = false;
          else setHeld(true);
        }}
        className="h-full w-full cursor-pointer object-cover"
      />
      {needsTap && (
        // Слой прозрачен для пальца: нажатие мимо кнопки доходит до кадра.
        <span className="pointer-events-none absolute inset-0 grid place-items-center">
          <button
            type="button"
            onClick={play}
            aria-label={playLabel}
            title={playLabel}
            className={vx("pointer-events-auto cursor-pointer rounded-full", VS_FOCUS)}
          >
            <span className={PLAY_GLYPH}>
              <FiPlay className="ml-0.5 text-lg" aria-hidden />
            </span>
          </button>
        </span>
      )}
      <span className="absolute bottom-0 right-0 flex">
        {!paused && (
          <button type="button" onClick={pause} aria-label={pauseLabel} title={pauseLabel} className={MEDIA_BTN}>
            <span className={MEDIA_GLYPH}>
              <FiPause className="size-3.5" aria-hidden />
            </span>
          </button>
        )}
        <button type="button" onClick={toggleSound} aria-label={soundLabel} title={soundLabel} className={MEDIA_BTN}>
          <span className={MEDIA_GLYPH}>
            {muted ? <FiVolumeX className="size-3.5" aria-hidden /> : <FiVolume2 className="size-3.5" aria-hidden />}
          </span>
        </button>
      </span>
    </>
  );
}

/**
 * Кадр карточки ленты: снятая сцена, превью пары «герой + сцена», замысел
 * своей сцены, герой поверх приглушённой сцены, кадр или обложка.
 *
 * Пропорции — как у будущего ролика: человек сразу видит, что получит в Reels
 * или на YouTube. Клиент: с вертикальным форматом карточка «поплыла» — кадр
 * 9:16 во всю ширину занимал пол-экрана телефона, и лента переставала
 * читаться. Поэтому высота кадра ограничена: вертикальный и квадратный встают
 * по центру в тех же пропорциях, карточка остаётся компактной.
 *
 * Поля вокруг кадра — чёрные, как у плеера: поверх видео и картинок всё
 * чёрно-белое в любой теме. Замысел своей сцены и пустая заглушка — часть
 * страницы и берут цвета темы.
 */
export default function SceneMedia({
  scene: s,
  working,
  aspect,
}: {
  scene: StudioScene;
  working: boolean;
  aspect: string;
}) {
  const { t } = useTranslation("common");
  const autoplay = useAutoplayAllowed();

  // Что в кадре — по порядку: первое подходящее.
  const frame: Frame = s.video
    ? "video"
    : s.preview_video && !working
      ? "preview"
      : s.custom_text && !s.keyframe && !working && s.status !== "failed"
        ? "concept"
        : !s.keyframe && s.preset.clip && !working && s.status === "draft"
          ? "hero"
          : s.keyframe || s.preset.poster
            ? "image"
            : "blank";

  return (
    <div
      className={vx(
        "flex justify-center overflow-hidden rounded-xl",
        frame === "concept" || frame === "blank" ? CLIP_BLANK : "bg-black",
      )}
    >
      <div
        className="relative overflow-hidden"
        style={
          aspect === "16:9"
            ? { aspectRatio: "16/9", width: "100%" }
            : { aspectRatio: aspect.replace(":", "/"), height: "11rem" }
        }
      >
        {frame === "video" ? (
          <ReadyVideo key={s.video} src={s.video} poster={s.keyframe} label={s.preset.title} />
        ) : frame === "preview" ? (
          <>
            {/* Клиент: до съёмки человек должен видеть сцену с героем в
                движении. Если эту пару уже снимали — показываем тот ролик,
                он заранее готов и ничего не стоит. */}
            <LazyClip
              src={s.preview_video ?? null}
              poster={s.keyframe || null}
              mode="visible"
              alt=""
              rounded="rounded-none"
              className="h-full w-full"
            />
            <span className={vx(VS_ON_MEDIA, "pointer-events-none absolute left-1.5 top-1.5")}>
              {t("studio_ui.preview_badge")}
            </span>
          </>
        ) : frame === "concept" ? (
          // Своя сцена до кадра: показать нечего, кроме замысла. Герой и
          // описание — ровно то, что пойдёт в съёмку.
          <div className="flex h-full w-full flex-col justify-between gap-2 bg-gradient-to-br from-accent/15 via-surface-2 to-surface-2 p-2.5">
            <p className="line-clamp-4 text-[12px] italic leading-snug text-foreground">«{s.custom_text}»</p>
            {s.character && (
              <span className="inline-flex w-fit max-w-full items-center gap-1 rounded-full border border-vs-ink/10 bg-surface py-0.5 pl-0.5 pr-2 text-[10px] font-medium text-foreground">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={s.character.image} alt="" className="size-4 shrink-0 rounded-full object-cover" />
                <span className="truncate">{s.character.name}</span>
              </span>
            )}
          </div>
        ) : frame === "hero" ? (
          <>
            {/* Ни ролика пары, ни кадра с героем. Раньше здесь в полный кадр
                играло превью сцены — а оно снято с героем библиотеки, и
                клиенту казалось, что выбранный герой «не поменялся». Теперь
                сцена приглушена фоном, а крупно поверх — именно тот герой, что
                закреплён за сценой. Увидеть его в самой сцене — кнопкой
                «Примерить» ниже. Фон декоративный: без автозапуска — только
                обложка, без кнопки запуска под размытием. */}
            <LazyClip
              src={autoplay ? (s.preset.clip ?? null) : null}
              poster={s.preset.poster || null}
              mode="visible"
              alt=""
              rounded="rounded-none"
              className="h-full w-full scale-105 opacity-35 blur-[2px]"
            />
            {s.character && (
              <span className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-1.5">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={s.character.image}
                  alt=""
                  className="aspect-square h-[62%] rounded-2xl object-cover shadow-lg ring-2 ring-accent/70"
                />
                <span className={vx(VS_ON_MEDIA, "max-w-[90%] truncate !text-[11px]")}>{s.character.name}</span>
              </span>
            )}
          </>
        ) : frame === "image" ? (
          <>
            {/* Пока своего кадра нет, показываем обложку сцены: у черновика
                ничего не грузится, и крутилка на его месте читалась как
                зависшая загрузка (жалоба клиента). Кадр с героем чуть движется
                камерой — это не действие героя, а живой предпросмотр, и
                подписан он честно. */}
            {s.keyframe && s.status === "draft" ? (
              // Движется, только пока карточка на экране (LiveFrame), — как кадр в витрине.
              <LiveFrame src={s.keyframe} />
            ) : (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={s.keyframe || s.preset.poster}
                alt=""
                loading="lazy"
                decoding="async"
                className={vx("h-full w-full object-cover", !s.keyframe && "opacity-70")}
              />
            )}
            {s.keyframe && s.status === "draft" && (
              <span className={vx(VS_ON_MEDIA, "pointer-events-none absolute left-1.5 top-1.5")}>
                {t("studio_ui.frame_badge")}
              </span>
            )}
            {working && (
              <span className="absolute inset-0 grid place-items-center bg-black/45 text-white" aria-hidden>
                <FiLoader className="animate-spin text-2xl motion-reduce:animate-none" />
              </span>
            )}
            {s.status === "failed" && (
              <span className="absolute inset-0 grid place-items-center bg-black/45" aria-hidden>
                <FiAlertTriangle className="text-2xl text-red-400" />
              </span>
            )}
          </>
        ) : (
          <span className="grid h-full w-full place-items-center text-2xl text-muted-2" aria-hidden>
            {s.status === "failed" ? (
              <FiAlertTriangle className="text-status-fail" />
            ) : working ? (
              <FiLoader className="animate-spin motion-reduce:animate-none" />
            ) : (
              <FiFilm />
            )}
          </span>
        )}
      </div>
    </div>
  );
}
