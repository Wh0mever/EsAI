"use client";

import { useCallback, useEffect, useEffectEvent, useId, useRef, useState, useSyncExternalStore } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { flushSync } from "react-dom";
import { useTranslation } from "react-i18next";
import { FiFilm, FiPlay } from "react-icons/fi";
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
} from "./playBudget";
import { VS_FOCUS, vx } from "./skin";
import { useAutoplayAllowed, useCanHover } from "./useAutoplayAllowed";

/**
 * Кадр с роликом, который не тратит трафик зря (§0.8).
 *
 * Сначала всегда лёгкая картинка. Сам <video> появляется в DOM, только когда
 * ролик действительно должен играть, и исчезает, как только перестал: вместе
 * с элементом браузер бросает и загрузку. Одновременно играет не больше
 * MAX_PLAYING роликов на вкладку (playBudget) — остальные ждут с постером.
 *
 * Режимы — когда ролик заводится сам:
 *   visible — карточка на экране хотя бы на 60% и не промелькнула мимо;
 *   hover   — на карточку навели курсор или пришли к ней с клавиатуры;
 *             на устройствах без курсора работает как visible;
 *   active  — пока active === true (кадр карусели); место в бюджете вне очереди.
 * В любом режиме ролик не заводится сам, если кадр виден меньше чем наполовину.
 *
 * Если человек просил «меньше движения», бережёт трафик или браузер запретил
 * автозапуск, сам ролик не стартует — на кадре круглая кнопка. Нажали —
 * играет этот, а запущенный так же до него останавливается; играет, пока
 * кадр хоть краем на экране.
 *
 * Кадр можно класть внутрь карточки-ссылки или карточки-кнопки (либо пометить
 * карточку атрибутом data-vs-clip-host): наведение и фокус тогда слушаются на
 * всей карточке, а кнопка запуска становится значком (кнопка внутри кнопки —
 * невалидная разметка) — первое нажатие по кадру заводит ролик, следующее
 * уже достаётся карточке.
 *
 * Размер задаёт className (aspect-video w-full, h-full w-full …); без него
 * кадр занимает родителя целиком. Родитель с absolute-подписями поверх кадра
 * должен быть position: relative сам — кадр их не позиционирует.
 *
 * Две темы. Всё, что лежит поверх картинки и ролика (кнопка запуска, чёрная
 * подложка под кадром), — чёрно-белое в любой теме: кадр тёмный всегда.
 * Заглушка, пока кадра нет, — часть страницы и берёт цвета темы.
 */

export type LazyClipMode = "visible" | "hover" | "active";

export type LazyClipProps = {
  /** Лёгкий ролик для ленты; null — показываем только картинку. */
  src: string | null;
  /** Картинка-постер; null — плёнка-заглушка, пока ролик не заиграет. */
  poster: string | null;
  mode: LazyClipMode;
  /** Для mode="active": этот кадр сейчас главный. */
  active?: boolean;
  /** Что в кадре — подпись картинки; пустая строка — кадр декоративный. */
  alt: string;
  className?: string;
  /** Скругление рамки; по умолчанию как у VS_MEDIA. */
  rounded?: string;
  /** cover — заполнить рамку (карточки), contain — показать кадр целиком. */
  fit?: "cover" | "contain";
};

/** Доля кадра на экране, с которой ролик заводится сам в режиме visible. */
const VISIBLE_SHARE = 0.6;
/** Ниже этой доли ролик не заводится сам ни в каком режиме. */
const STAGE_SHARE = 0.5;
/**
 * Столько карточка должна простоять на экране, чтобы завести ролик сама. Без
 * этого при быстром пролистывании галереи каждая промелькнувшая карточка
 * успевала бы создать <video> и начать загрузку, которую тут же бросит.
 * Постер всё это время на месте, так что ожидания не видно.
 */
const DWELL_MS = 280;
/** Кадр лежит внутри ссылки или кнопки: своя кнопка запуска там невозможна. */
const INTERACTIVE_SELECTOR = "a[href], button, [role='button']";
/** Карточка, наведение и фокус которой заводят ролик, если это не сама ссылка-кнопка. */
const HOST_SELECTOR = "[data-vs-clip-host]";

/**
 * Пустой кадр (картинки нет или она ещё не пришла). На светлой сцене тон на
 * ступень темнее, чем у карточек: кадр галереи лежит прямо на «бумаге», и
 * более светлая заглушка на ней пропала бы.
 */
const BLANK = "bg-surface-3 dark:bg-surface-2";
/**
 * Подложка под кадром. Картинка проявляется за полсекунды. В тёмной теме она
 * проявляется из чёрного — как и было. На светлой странице чёрная плитка на
 * месте светлой заглушки мигнула бы у каждой карточки, поэтому там подложка
 * темнеет тем же переходом, что и картинка, и чёрной (поля у fit="contain")
 * становится, когда кадр уже закрыт.
 */
const BACKING = "transition-colors duration-500";
const BACKING_BARE = "bg-surface-3 dark:bg-black";

const idle = () => 0;

type ClipVideoProps = {
  src: string;
  fit: "cover" | "contain";
  shown: boolean;
  onShown: (shown: boolean) => void;
  onBlocked: () => void;
  onFailed: () => void;
};

/** Сам ролик. Живёт в DOM, только пока играет; уход из DOM и есть остановка. */
function ClipVideo({ src, fit, shown, onShown, onBlocked, onFailed }: ClipVideoProps) {
  const ref = useRef<HTMLVideoElement>(null);
  const blocked = useEffectEvent(onBlocked);
  const hide = useEffectEvent(() => onShown(false));

  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    let gone = false;
    const start = () => {
      const playing = video.play();
      if (!playing) return;
      playing.catch((err: unknown) => {
        // AbortError — остановили мы сами (ушёл с экрана, скрыта вкладка).
        // Отказ браузера заводить ролик без нажатия — только NotAllowedError.
        if (!gone && err instanceof DOMException && err.name === "NotAllowedError") blocked();
      });
    };
    const onVisibility = () => {
      if (document.hidden) video.pause();
      else start();
    };
    // Адрес ставим здесь, а не атрибутом в разметке: при уходе мы его снимаем,
    // и повторный запуск эффекта (StrictMode, смена ролика) обязан вернуть его сам.
    video.muted = true;
    video.src = src;
    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      gone = true;
      document.removeEventListener("visibilitychange", onVisibility);
      // pause() загрузку не обрывает — браузер докачал бы ролик, которого уже
      // нет на экране. Пустой src + load() обрывают.
      video.pause();
      video.removeAttribute("src");
      video.load();
      hide();
    };
  }, [src]);

  return (
    <video
      ref={ref}
      muted
      loop
      playsInline
      preload="metadata"
      aria-hidden
      tabIndex={-1}
      onLoadedData={() => onShown(true)}
      onError={onFailed}
      className={vx(
        "pointer-events-none absolute inset-0 h-full w-full transition-opacity duration-300",
        fit === "contain" ? "object-contain" : "object-cover",
        shown ? "opacity-100" : "opacity-0",
      )}
    />
  );
}

export default function LazyClip({
  src,
  poster,
  mode,
  active = false,
  alt,
  className,
  rounded = "rounded-xl",
  fit = "cover",
}: LazyClipProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const id = useId();
  const allowed = useAutoplayAllowed();
  const canHover = useCanHover();

  const [root, setRoot] = useState<HTMLSpanElement | null>(null);
  const [host, setHost] = useState<HTMLElement | null>(null);
  // До монтирования считаем, что кадр внутри кнопки: значок безопасен в любой разметке.
  const [nested, setNested] = useState(true);
  const mount = useCallback((el: HTMLSpanElement | null) => {
    const card = el ? el.closest<HTMLElement>(INTERACTIVE_SELECTOR) : null;
    setRoot(el);
    setHost(el ? (el.closest<HTMLElement>(HOST_SELECTOR) ?? card) : null);
    setNested(el === null || card !== null);
  }, []);

  // Без IntersectionObserver считаем кадр видимым: лучше лишний ролик, чем пустая карточка.
  const [inView, setInView] = useState(() => typeof IntersectionObserver === "undefined");
  // Хоть краем на экране: только тогда заглушка «проявляется» — за экраном анимации не место.
  const [seen, setSeen] = useState(() => typeof IntersectionObserver === "undefined");
  const [hovered, setHovered] = useState(false);
  // Состояния «по адресу»: сменился постер или ролик — прежние отметки сами теряют силу.
  const [loadedPoster, setLoadedPoster] = useState<string | null>(null);
  const [brokenPoster, setBrokenPoster] = useState<string | null>(null);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const [videoShown, setVideoShown] = useState(false);

  const state = useSyncExternalStore(subscribePlay, () => playState(id), idle);
  const playing = (state & PLAY_ON) !== 0;
  const blocked = (state & PLAY_BLOCKED) !== 0;

  // «hover» без курсора (телефон) — это «visible»: навести там нечем.
  const byHover = mode === "hover" && canHover;
  const share = mode === "visible" || (mode === "hover" && !canHover) ? VISIBLE_SHARE : STAGE_SHARE;

  const playable = src !== null && src !== "" && failedSrc !== src;
  // Кадру вообще положено играть: в карусели — только активному.
  const staged = mode !== "active" || active;
  const auto = playable && staged && inView && allowed && !blocked && (!byHover || hovered);

  useEffect(() => {
    if (!root || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        const last = entries[entries.length - 1];
        setSeen(last.isIntersecting);
        setInView(last.isIntersecting && last.intersectionRatio >= share);
        // Ролик не загрузился из-за сети — когда кадр вернётся на экран, пробуем снова.
        if (!last.isIntersecting) setFailedSrc(null);
      },
      { threshold: [0, share] },
    );
    io.observe(root);
    return () => io.disconnect();
  }, [root, share]);

  useEffect(() => {
    if (!byHover || !root) return;
    const target = host ?? root;
    const enter = (e: PointerEvent) => {
      if (e.pointerType !== "touch") setHovered(true);
    };
    const leave = () => setHovered(false);
    const focusIn = () => {
      // Фокус от клика мышью остаётся и после ухода курсора — такой не считаем.
      let keyboard = true;
      try {
        keyboard = target.matches(":focus-visible") || target.querySelector(":focus-visible") !== null;
      } catch {
        // старый браузер без :focus-visible — считаем любой фокус клавиатурным
      }
      if (keyboard) setHovered(true);
    };
    target.addEventListener("pointerenter", enter);
    target.addEventListener("pointerleave", leave);
    target.addEventListener("focusin", focusIn);
    target.addEventListener("focusout", leave);
    return () => {
      target.removeEventListener("pointerenter", enter);
      target.removeEventListener("pointerleave", leave);
      target.removeEventListener("focusin", focusIn);
      target.removeEventListener("focusout", leave);
      setHovered(false);
    };
  }, [byHover, root, host]);

  useEffect(() => {
    // Совсем ушёл с экрана или перестал быть активным — останавливаем и
    // запущенный нажатием. Виден краем — сам не играет, но начатый доигрывает.
    if (!playable || !staged || !seen) {
      releasePlay(id);
      return;
    }
    if (!auto) {
      releaseAuto(id);
      return;
    }
    // Кадр карусели и карточка под курсором заводятся сразу: карусель уже
    // выждала сама, а курсор — выбор человека. Ждут только карточки, которые
    // заводит одна лишь прокрутка.
    if (mode === "active" || byHover) {
      requestPlay(id, mode === "active");
      return;
    }
    const timer = setTimeout(() => requestPlay(id), DWELL_MS);
    return () => clearTimeout(timer);
  }, [id, playable, staged, seen, auto, mode, byHover]);

  useEffect(() => () => releasePlay(id), [id]);

  const onBlocked = useCallback(() => {
    markAutoplayBlocked();
    // Запущенный нажатием тоже не пошёл — вернём кнопку, а не пустой кадр.
    releasePlay(id);
  }, [id]);

  const onFailed = useCallback(() => {
    setFailedSrc(src);
    releasePlay(id);
  }, [id, src]);

  const posterMount = useCallback(
    (img: HTMLImageElement | null) => {
      // Картинка из кэша могла загрузиться раньше, чем React повесил onLoad.
      if (img && img.complete && img.naturalWidth > 0) setLoadedPoster(poster);
    },
    [poster],
  );

  const start = (e: ReactMouseEvent<HTMLElement>) => {
    e.preventDefault();
    e.stopPropagation();
    // Кнопка запуска сейчас исчезнет. Нажали с клавиатуры — фокус на ней, и он
    // упал бы на <body>: стрелки карусели перестали бы листать. Отдаём его
    // ближайшему предку, который умеет его держать (сама карусель). От мыши и
    // пальца фокуса на кнопке может не быть — тогда не трогаем ничего.
    const el = e.currentTarget;
    if (el === document.activeElement) {
      el.parentElement?.closest<HTMLElement>("[tabindex]")?.focus({ preventScroll: true });
    }
    // Ролик должен появиться и стартовать внутри этого же нажатия: iOS в
    // режиме энергосбережения иначе откажет и ему.
    flushSync(() => requestSolo(id));
  };

  const hasPoster = poster !== null && poster !== "" && brokenPoster !== poster;
  const posterReady = hasPoster && loadedPoster === poster;
  const covered = posterReady || (playing && videoShown);
  const loading = (hasPoster && !posterReady) || (playing && !videoShown);
  const needsTap = playable && !playing && (!allowed || blocked) && staged;
  const playLabel = t("run.actions.play", { defaultValue: "Смотреть" });
  const positioned = /(?:^|\s)(?:absolute|fixed|sticky)(?:\s|$)/.test(className || "");

  // Без размытия фона, как и VS_ON_MEDIA: при выключенном автозапуске значок
  // стоит на каждой карточке галереи.
  const playGlyph = (
    <span className="grid size-11 place-items-center rounded-full bg-black/60 text-white transition-transform duration-200 group-hover/clip:scale-110">
      <FiPlay className="ml-0.5 text-lg" aria-hidden />
    </span>
  );

  // Корень — span: кадр часто лежит внутри кнопки, а блочный тег там невалиден.
  return (
    <span
      ref={mount}
      onClick={needsTap && nested ? start : undefined}
      className={vx(
        "group/clip block overflow-hidden",
        BACKING,
        covered ? "bg-black" : BACKING_BARE,
        !positioned && "relative",
        rounded,
        className || "h-full w-full",
      )}
    >
      {!covered && (
        <span
          aria-hidden
          className={vx(
            "absolute inset-0 grid place-items-center text-2xl text-vs-ink/20",
            loading && seen ? "vs-film" : BLANK,
          )}
        >
          {!loading && <FiFilm />}
        </span>
      )}

      {hasPoster ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          ref={posterMount}
          src={poster}
          alt={alt}
          loading="lazy"
          decoding="async"
          draggable={false}
          onLoad={() => setLoadedPoster(poster)}
          onError={() => setBrokenPoster(poster)}
          className={vx(
            "absolute inset-0 h-full w-full transition-opacity duration-500",
            fit === "contain" ? "object-contain" : "object-cover",
            posterReady ? "opacity-100" : "opacity-0",
          )}
        />
      ) : (
        alt && <span className="sr-only">{alt}</span>
      )}

      {playing && playable && (
        <ClipVideo
          src={src}
          fit={fit}
          shown={videoShown}
          onShown={setVideoShown}
          onBlocked={onBlocked}
          onFailed={onFailed}
        />
      )}

      {needsTap &&
        (nested ? (
          <span aria-hidden className="pointer-events-none absolute inset-0 grid place-items-center">
            {playGlyph}
          </span>
        ) : (
          <button
            type="button"
            onClick={start}
            aria-label={playLabel}
            title={playLabel}
            className={vx("absolute inset-0 grid cursor-pointer place-items-center focus-visible:ring-inset", VS_FOCUS, rounded)}
          >
            {playGlyph}
          </button>
        ))}
    </span>
  );
}
