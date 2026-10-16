"use client";

import { useTranslation } from "react-i18next";
import SaveMediaButton from "@/components/ui/SaveMediaButton";
import {
  FiArrowLeft,
  FiArrowRight,
  FiCheck,
  FiClock,
  FiFilm,
  FiLoader,
  FiMic,
  FiPlay,
  FiRefreshCw,
  FiTrash2,
  FiX,
  FiZap,
} from "react-icons/fi";
import { EDGE_FADE, useEdgeFade } from "@/components/vstudio/home/strip/useEdgeFade";
import {
  VS_BTN_GHOST,
  VS_CARD,
  VS_FOCUS,
  VS_ICON_BTN,
  VS_INPUT,
  VS_LABEL,
  VS_PILL_ON,
  vx,
} from "@/components/vstudio/ui/skin";
import { CS_ANCHOR, CS_CARD_BTN, CS_EMPTY, CS_STRIP } from "./ui/cartoonSkin";
import SceneMedia from "./timeline/SceneMedia";
import {
  DOCK_RU,
  configLabel,
  dialogueMaxLength,
  type SceneConfig,
  type SceneShot,
} from "./dockLogic";

/** Сообщение у строки ленты: отказ или подсказка после действия с этой сценой.
 *  price — у «Цена изменилась: теперь N кр»: N (null — числа нет); по нему сообщение
 *  уходит, когда цена строки стала другой (dockLogic.settlePriceNotes). */
export type SceneNote = { text: string; tone: "error" | "info"; price?: number | null };

export type StudioScene = {
  id: number;
  order: number;
  preset: {
    id: number;
    title: string;
    /** null — цены сейчас нет (режим цен «наценка», себестоимость модели неизвестна). */
    credits?: number | null;
    duration?: number;
    /** Обложка сцены из библиотеки — то, что видно у черновика. */
    poster?: string;
    /** Ролик самой сцены (с героем библиотеки) — движение в ленте, пока своего нет. */
    clip?: string;
  };
  /** Своя сцена: что делает герой, словами человека. */
  custom_text?: string;
  /** Что герой говорит в этой сцене: играется в кадре и звучит голосом. */
  dialogue?: string;
  /** Кем снимается эта сцена: свой герой или герой всего мультфильма. */
  character?: { id: number; name: string; image: string } | null;
  keyframe: string;
  /** Готовый ролик этой пары «герой + сцена», снятый раньше кем-то, — превью в движении до съёмки. */
  preview_video?: string;
  video: string;
  status: "draft" | "new" | "keyframe" | "video" | "ready" | "failed";
  error: string;
  credits_spent: number;
  /** Сколько спишет съёмка прямо сейчас (с готовым кадром — только видео). null — цены нет. */
  render_credits?: number | null;
  /** Сколько звуковых дорожек у сцены (голоса, музыка, эффекты). */
  audio_count?: number;
  /** Своя длительность сцены, секунды; null — как у мультфильма (или сцены библиотеки). */
  duration?: number | null;
  /** Чем сцена снимется по «Снять» сейчас; у снимающейся — чем снимается. */
  config?: SceneConfig | null;
  /** Снимок последнего «Снять»: чем снята или снимается; null — снята до дока. */
  shot?: SceneShot | null;
  /** Цены нет (режим «наценка», себестоимость модели неизвестна). */
  price_unavailable?: boolean;
};

/** Выбор длительности в карточке: что умеет модель сцены и сколько «по умолчанию». */
export type SceneDurationChoice = { options: number[]; fallback: number | null };

/**
 * SceneTimeline — лента сцен будущего мультфильма.
 *
 * Кадр показывается СРАЗУ, как только нарисован, ещё до готового ролика: так
 * человек за секунды видит, что получит, а не смотрит в пустой прямоугольник
 * пару минут. Готовая сцена превращается в плеер прямо в ленте.
 *
 * Порядок меняется стрелками, а не перетаскиванием: на телефоне drag-and-drop
 * в горизонтальном списке дерётся со скроллом, а стрелки работают везде
 * одинаково.
 *
 * На телефоне лента листается вбок (карточки по 240 px, с притяжением к краю),
 * с 768 px — сетка: ряд не прячет сцены за краем, а широкий экран не пустует.
 */

/** Ключ подписи состояния — сам текст берётся из локали (studio_ui.st_*). */
const STATUS_KEY: Record<StudioScene["status"], string> = {
  draft: "st_draft",
  new: "st_new",
  keyframe: "st_keyframe",
  video: "st_video",
  ready: "st_ready",
  failed: "st_failed",
};

/** Выпадающий список в карточке: 44 px на телефоне, шрифт 16 px — иначе iOS приближает страницу. */
const SELECT = vx(
  VS_INPUT,
  "!min-h-11 min-w-0 cursor-pointer !px-2 !text-[12px] max-sm:!text-base md:!min-h-8 disabled:cursor-not-allowed disabled:opacity-60",
);
/** Значок в нижнем ряду карточки: 44 px на телефоне, 36 px с 768 px. */
const ROW_ICON = vx(VS_ICON_BTN, "md:!size-9 aria-disabled:cursor-not-allowed aria-disabled:opacity-50");
/** «Снять сцену» — золотой контур, а не заливка: золотая кнопка на экране одна, в доке. */
const RENDER_BTN = vx(VS_BTN_GHOST, VS_PILL_ON, "w-full !font-semibold hover:!bg-accent/[0.16]");
/** «Переснять с репликой» — тихая кнопка с золотой подписью: её стоит заметить. */
const RESHOOT_LINE_BTN = vx(CS_CARD_BTN, "!border-vs-accent/45 !text-vs-accent hover:!bg-accent/[0.1]");
const SPIN = "animate-spin motion-reduce:animate-none";

export default function SceneTimeline({
  scenes,
  busyIds,
  onMove,
  onRetry,
  onDelete,
  onRender,
  characters = [],
  onPickCharacter,
  onFrame,
  framingId = null,
  frameCredits,
  onTryOn,
  tryingOnId = null,
  tryOnLabel,
  onAudio,
  onRedraw,
  onDialogue,
  aspect = "16:9",
  durationFor,
  onDuration,
  repricing = false,
  notes,
  onDismissNote,
  label,
}: {
  /** Док или формат едут на сервер: цены строк ещё прежние — «Снять» и «Переснять» ждут новые. */
  repricing?: boolean;
  /** Сообщения у строк (по id сцены): отказ «Снять», «цена изменилась», не сохранилось. */
  notes?: Record<number, SceneNote>;
  onDismissNote?: (scene: StudioScene) => void;
  /** Длительность сцены: варианты модели сцены. null — выбора нет (модель вне дока). */
  durationFor?: (scene: StudioScene) => SceneDurationChoice | null;
  /** Выбрали длительность (null — по умолчанию). У снятой сцены родитель спросит про пересъёмку. */
  onDuration?: (scene: StudioScene, value: number | null) => void;
  /** Формат мультфильма: карточка показывает кадр в тех же пропорциях. */
  aspect?: string;
  /** Сохранить реплику героя. Нет — поле не показываем (гость без проекта). */
  onDialogue?: (scene: StudioScene, text: string) => void;
  /** Перерисовать кадр сцены: прежний не понравился или вышел не тот герой. */
  onRedraw?: (scene: StudioScene) => void;
  /** Открыть звук сцены. Нет — озвучка выключена, кнопку не показываем. */
  onAudio?: (scene: StudioScene) => void;
  /** Примерить героя сцены на сцену из библиотеки прямо из ленты. */
  onTryOn?: (scene: StudioScene) => void;
  /** id сцены библиотеки (preset), которая сейчас примеряется. */
  tryingOnId?: number | null;
  tryOnLabel?: string;
  /** Цена кадра своей сцены. Нет — кнопка без цены: число «по памяти» разошлось бы с сервером. */
  frameCredits?: number | null;
  /** Своя сцена: нарисовать кадр до съёмки (цена — frameCredits). */
  onFrame?: (scene: StudioScene) => void;
  framingId?: number | null;
  scenes: StudioScene[];
  busyIds: Set<number>;
  onMove: (scene: StudioScene, dir: -1 | 1) => void;
  onRetry: (scene: StudioScene) => void;
  onDelete: (scene: StudioScene) => void;
  onRender: (scene: StudioScene) => void;
  /** Кого можно поставить на эту сцену. */
  characters?: { id: number; name: string; image: string }[];
  onPickCharacter?: (scene: StudioScene, characterId: number) => void;
  /** Подпись списка для экранного диктора: заголовок секции. */
  label?: string;
}) {
  const { t } = useTranslation("common");
  const { attach, fade } = useEdgeFade<HTMLDivElement>();
  const seconds = (n: number) => t("studio_ui.dock_seconds", { defaultValue: DOCK_RU["studio_ui.dock_seconds"], n });
  const cfgText = (c: SceneConfig) => [configLabel(c), seconds(c.duration)].filter(Boolean).join(" · ");
  const creditsShort = t("studio_ui.credits_short");

  if (!scenes.length) {
    return (
      <div className={CS_EMPTY}>
        <FiFilm className="size-6 text-muted-2" aria-hidden />
        {t("studio_ui.timeline_empty")}
      </div>
    );
  }

  return (
    // Поля по вертикали — чтобы лента не срезала кольцо фокуса карточек.
    <div
      ref={attach}
      className={vx(
        CS_STRIP,
        EDGE_FADE[fade],
        // proximity, а не mandatory: в карточках поля и выбор, и обязательная привязка
        // спорила бы с прокруткой к полю, когда открывается клавиатура.
        "snap-x snap-proximity scroll-px-4 sm:scroll-px-6 md:mx-0 md:snap-none md:overflow-visible md:px-0",
      )}
    >
      <ol
        aria-label={label}
        className="flex w-max gap-3 md:grid md:w-auto md:grid-cols-[repeat(auto-fill,minmax(224px,1fr))]"
      >
        {scenes.map((s, i) => {
          const working = s.status === "new" || s.status === "keyframe" || s.status === "video";
          const busy = busyIds.has(s.id);
          // Сервер прислал null: себестоимость модели неизвестна, съёмку он всё равно
          // отклонит. У гостя цены просто ещё нет (undefined) — его ведём ко входу.
          const noPrice = s.render_credits === null || s.preset.credits === null;
          // Платные кнопки: без цены или пока цена пересчитывается — не жмутся.
          const payLocked = busy || noPrice || repricing;
          const reshootCredits =
            s.render_credits !== undefined
              ? s.render_credits
              : s.preset.credits != null && frameCredits != null
              ? Math.max(1, s.preset.credits - frameCredits)
              : null;
          // Цена строки — ровно то, что спишет «Снять» сейчас (с готовым кадром — только видео).
          const rowCredits = s.render_credits ?? s.preset.credits;
          // Снимающаяся сцена идёт по снимку — её длительность уже не поменять.
          const choice = !working && onDuration ? durationFor?.(s) ?? null : null;
          const own = s.duration ?? null;
          const current = s.config?.duration ?? s.preset.duration ?? null;
          const defaultSeconds = own == null ? current : choice?.fallback ?? null;
          const shot = s.shot ?? (working ? s.config : null);
          // У снимающейся сцены — цена снимка: ровно столько и спишется.
          const shotText = shot
            ? [cfgText(shot), working && typeof s.shot?.credits_planned === "number"
                ? `${s.shot.credits_planned} ${creditsShort}`
                : ""].filter(Boolean).join(" · ")
            : "";
          const note = notes?.[s.id];
          // Реплика длиннее сцены не уместится, а больше 300 знаков сервер не сохранит.
          const dialogueMax = dialogueMaxLength(s.preset.duration);
          const heroLabel = t("studio_ui.scene_hero_change");
          const durationLabel = t("studio_ui.scene_duration", { defaultValue: DOCK_RU["studio_ui.scene_duration"] });
          return (
            <li
              key={s.id}
              // Поля прокрутки — для «+ В ленту»: новая карточка встаёт ниже затухания под
              // верхней строкой и выше затухания над доком (CS_ANCHOR).
              className={vx(VS_CARD, CS_ANCHOR, "flex w-60 shrink-0 snap-start flex-col gap-2.5 p-2.5 md:w-auto")}
            >
              <div className="flex min-w-0 items-center gap-2">
                <span className="grid size-5 shrink-0 place-items-center rounded-full bg-accent text-[10px] font-bold tabular-nums text-on-accent">
                  {i + 1}
                </span>
                <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-foreground" title={s.preset.title}>
                  {s.preset.title}
                </span>
              </div>

              {/* Герой этой сцены. У черновика его можно сменить — так во второй
                  сцене появляется другой персонаж, и история собирается из
                  нескольких героев, а не одного. Список сам показывает имя. */}
              {s.character && (
                <div className="flex min-w-0 items-center gap-2">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={s.character.image}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    className="size-6 shrink-0 rounded-full bg-surface-2 object-cover ring-1 ring-vs-ink/10"
                  />
                  {s.status === "draft" && characters.length > 1 && onPickCharacter ? (
                    <select
                      value={s.character.id}
                      onChange={(e) => onPickCharacter(s, Number(e.target.value))}
                      aria-label={heroLabel}
                      title={heroLabel}
                      className={vx(SELECT, "flex-1")}
                    >
                      {characters.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="min-w-0 truncate text-[12px] text-muted">{s.character.name}</span>
                  )}
                </div>
              )}

              <SceneMedia scene={s} working={working} aspect={aspect} />

              <div className="flex min-h-5 min-w-0 items-center gap-1.5 text-[12px]">
                {s.status === "ready" ? (
                  <span className="inline-flex items-center gap-1 font-medium text-status-ok">
                    <FiCheck aria-hidden /> {t("studio_ui.st_ready")}
                  </span>
                ) : s.status === "failed" ? (
                  <span className="truncate font-medium text-status-fail">{t("studio_ui.st_failed")}</span>
                ) : s.status === "draft" ? (
                  // Чем снимется: модель и качество из дока (длительность — ниже, её можно выбрать).
                  <span className="truncate text-muted-2">{configLabel(s.config)}</span>
                ) : (
                  <span className="truncate text-status-progress">{t(`studio_ui.${STATUS_KEY[s.status]}`)}…</span>
                )}
                {s.credits_spent > 0 && (
                  <span className="ml-auto shrink-0 tabular-nums text-muted-2">
                    {s.credits_spent} {creditsShort}
                  </span>
                )}
              </div>

              {/* Чем снята или снимается сцена: снимок «Снять» — модель, качество, длительность. */}
              {shot && (working || s.status === "ready") && (
                <p className="-mt-1.5 truncate text-[11px] text-muted-2" title={shotText}>
                  {t(working ? "studio_ui.scene_shot_working" : "studio_ui.scene_shot_ready", {
                    defaultValue: DOCK_RU[working ? "studio_ui.scene_shot_working" : "studio_ui.scene_shot_ready"],
                    config: shotText,
                  })}
                </p>
              )}

              {/* Длительность этой сцены и её цена. Своя длительность подсвечена; «по
                  умолчанию» — как у мультфильма. У снятой сцены новая длительность —
                  это новая съёмка: родитель спросит, прежде чем снимать. */}
              {(choice || s.status === "draft" || s.status === "failed") && (
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]">
                  {choice && onDuration ? (
                    <label className="flex min-w-0 items-center gap-1.5 text-muted-2">
                      <FiClock className="shrink-0" aria-hidden />
                      <span className="sr-only">{durationLabel}</span>
                      <select
                        value={own == null ? "" : String(own)}
                        onChange={(e) => onDuration(s, e.target.value === "" ? null : Number(e.target.value))}
                        disabled={busy}
                        title={durationLabel}
                        className={vx(SELECT, own != null && "!border-vs-accent/60")}
                      >
                        <option value="">
                          {defaultSeconds != null
                            ? t("studio_ui.scene_duration_default", {
                                defaultValue: DOCK_RU["studio_ui.scene_duration_default"],
                                n: defaultSeconds,
                              })
                            : t("studio_ui.scene_duration_default_plain", {
                                defaultValue: DOCK_RU["studio_ui.scene_duration_default_plain"],
                              })}
                        </option>
                        {choice.options.map((n) => (
                          <option key={n} value={n}>
                            {seconds(n)}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : current != null ? (
                    <span className="inline-flex items-center gap-1.5 text-muted-2">
                      <FiClock aria-hidden />
                      {seconds(current)}
                    </span>
                  ) : null}
                  {(s.status === "draft" || s.status === "failed") && (
                    <span
                      className={vx(
                        "ml-auto inline-flex shrink-0 items-center gap-1 tabular-nums",
                        noPrice ? "text-muted-2" : "font-semibold text-foreground",
                      )}
                    >
                      {noPrice ? (
                        t("studio_ui.price_unavailable", { defaultValue: "Цена сейчас недоступна" })
                      ) : rowCredits != null ? (
                        <>
                          <FiZap className="text-vs-accent" aria-hidden />
                          {rowCredits} {creditsShort}
                        </>
                      ) : null}
                    </span>
                  )}
                </div>
              )}

              {/* Причина — текстом, а не подсказкой при наведении: на телефоне
                  наведения нет, и человек видел одно «Не получилось». */}
              {s.status === "failed" && s.error && (
                <p className="line-clamp-4 text-[12px] leading-snug text-status-fail">{s.error}</p>
              )}

              {/* Ответ на то, что человек только что нажал у этой сцены («цена
                  изменилась», «уже снята», «не сохранилось») — здесь, у кнопки, а не
                  вверху страницы: с телефона тот блок не виден вовсе. role="alert" у обоих
                  тонов: заметка появляется вместе с текстом, а такой role="status" многие
                  чтецы не объявляют — «уже снята» не было бы слышно. Цвета — токены статусов:
                  в светлой теме держат контраст 4.5:1. */}
              {note && (
                <div
                  className={vx(
                    "flex items-start gap-1 rounded-xl border py-1.5 pl-2.5 pr-1",
                    note.tone === "error" ? "border-status-fail/35 bg-status-fail/[0.06]" : "border-status-wait/35 bg-status-wait/[0.06]",
                  )}
                >
                  <p
                    role="alert"
                    className={vx(
                      "min-w-0 flex-1 py-0.5 text-[12px] leading-snug",
                      note.tone === "error" ? "text-status-fail" : "text-status-wait",
                    )}
                  >
                    {note.text}
                  </p>
                  {onDismissNote && (
                    <button
                      type="button"
                      onClick={() => onDismissNote(s)}
                      aria-label={t("studio_ui.dock_hide_notice", { defaultValue: DOCK_RU["studio_ui.dock_hide_notice"] })}
                      className={vx(
                        "-my-1 grid size-11 shrink-0 cursor-pointer place-items-center rounded-full text-muted transition-colors hover:bg-vs-ink/[0.08] hover:text-foreground md:my-0 md:size-7",
                        VS_FOCUS,
                      )}
                    >
                      <FiX aria-hidden />
                    </button>
                  )}
                </div>
              )}

              {/* Черновик снимается отсюда: клиент просил, чтобы человек сначала
                  набирал ленту, а потом генерировал любую сцену из неё. */}
              {/* Своя сцена: кадр до съёмки — увидеть, что получится, прежде чем
                  платить за видео. Потом этот же кадр идёт в съёмку. */}
              {/* Сцена из библиотеки, а кадра с героем ещё нет: примерить прямо из
                  ленты, с героем именно этой сцены. */}
              {s.status === "draft" && !s.custom_text && !s.keyframe && !s.preview_video && s.character && onTryOn && (
                <button
                  type="button"
                  onClick={() => onTryOn(s)}
                  disabled={busy || tryingOnId !== null}
                  aria-busy={tryingOnId === s.preset.id || undefined}
                  className={CS_CARD_BTN}
                >
                  {tryingOnId === s.preset.id ? <FiLoader className={SPIN} aria-hidden /> : <FiFilm aria-hidden />}
                  {tryOnLabel || t("studio_ui.try_on")}
                </button>
              )}
              {s.status === "draft" && s.custom_text && !s.keyframe && onFrame && (
                <button
                  type="button"
                  onClick={() => onFrame(s)}
                  disabled={busy || framingId !== null}
                  aria-busy={framingId === s.id || undefined}
                  className={CS_CARD_BTN}
                >
                  {framingId === s.id ? <FiLoader className={SPIN} aria-hidden /> : <FiFilm aria-hidden />}
                  {frameCredits != null
                    ? t("studio_ui.frame_btn", { credits: frameCredits })
                    : t("studio_ui.frame_btn_plain", { defaultValue: "Кадр" })}
                </button>
              )}
              {/* Реплика героя. Клиент: мультфильм должен смотреться как
                  мультфильм — значит герой должен говорить, и говорить то, что
                  задумал человек. Эта же строчка уходит в съёмку и в озвучку. */}
              {(s.status === "draft" || s.status === "ready" || s.status === "failed") && onDialogue && (
                <label className="flex flex-col gap-1.5">
                  <span className="flex items-baseline justify-between gap-2">
                    <span className={VS_LABEL}>{t("studio_ui.dialogue_label")}</span>
                    <span className="shrink-0 text-[11px] text-muted-2">
                      {t("studio_ui.dialogue_fit", { seconds: s.preset.duration || 5 })}
                    </span>
                  </span>
                  <textarea
                    defaultValue={s.dialogue || ""}
                    onBlur={(e) => {
                      const next = e.target.value.trim().slice(0, 300);
                      if (next !== (s.dialogue || "")) onDialogue(s, next);
                    }}
                    rows={2}
                    // Речь — это 2-3 слова в секунду: реплика длиннее сцены не
                    // поместится, и модель оборвёт её на полуслове. И не больше 300
                    // знаков: длиннее сервер не сохранит, а обрезать молча нельзя.
                    maxLength={dialogueMax}
                    placeholder={t("studio_ui.dialogue_ph")}
                    className={vx(VS_INPUT, "!min-h-16 resize-none py-2 leading-snug !text-[13px] max-sm:!text-base")}
                  />
                  {/* Клиент: «а нельзя, чтоб рот открывался?» Можно — но только
                      если реплику произносит сама модель при съёмке. */}
                  <span className="text-[11px] leading-snug text-muted-2">
                    {t(s.status === "ready" ? "studio_ui.dialogue_hint_ready" : "studio_ui.dialogue_hint")}
                  </span>
                </label>
              )}
              {/* Готовая сцена с репликой: переснять, чтобы герой её произнёс. */}
              {s.status === "ready" && Boolean(s.dialogue) && (
                <button
                  type="button"
                  onClick={() => onRetry(s)}
                  disabled={payLocked}
                  aria-busy={busy || undefined}
                  className={RESHOOT_LINE_BTN}
                >
                  {busy ? <FiLoader className={SPIN} aria-hidden /> : <FiRefreshCw aria-hidden />}
                  {reshootCredits != null
                    ? t("studio_ui.reshoot_with_line", { credits: reshootCredits })
                    : t("studio_ui.reshoot_with_line_plain", { defaultValue: "Переснять с репликой" })}
                </button>
              )}
              {/* Готовая сцена без реплики: «Переснять» — подписанной кнопкой с ценой. Раньше
                  это был значок ↻ с подсказкой при наведении, а на телефоне наведения нет —
                  и отказ «переснять можно кнопкой «Переснять»» указывал в никуда. */}
              {s.status === "ready" && !s.dialogue && (
                <button
                  type="button"
                  onClick={() => onRetry(s)}
                  disabled={payLocked}
                  aria-busy={busy || undefined}
                  title={t("studio_ui.retry")}
                  className={CS_CARD_BTN}
                >
                  <FiRefreshCw className={busy ? SPIN : ""} aria-hidden />
                  {reshootCredits != null
                    ? t("studio_ui.reshoot_btn", { defaultValue: DOCK_RU["studio_ui.reshoot_btn"], credits: reshootCredits })
                    : t("studio_ui.reshoot_btn_plain", { defaultValue: DOCK_RU["studio_ui.reshoot_btn_plain"] })}
                </button>
              )}

              {/* Кадр уже есть, но не тот: нарисовать заново. Без этого
                  неудачный кадр можно было убрать только вместе со сценой. */}
              {s.status === "draft" && s.keyframe && onRedraw && (
                <button
                  type="button"
                  onClick={() => onRedraw(s)}
                  disabled={busy || tryingOnId !== null || framingId !== null}
                  className={CS_CARD_BTN}
                >
                  {busy || tryingOnId === s.preset.id || framingId === s.id ? (
                    <FiLoader className={SPIN} aria-hidden />
                  ) : (
                    <FiRefreshCw aria-hidden />
                  )}
                  {frameCredits != null
                    ? t("studio_ui.tl_redraw", { defaultValue: "Кадр заново · {{credits}} кр", credits: frameCredits })
                    : t("studio_ui.tl_redraw_plain", { defaultValue: "Кадр заново" })}
                </button>
              )}
              {s.status === "draft" && (
                <button
                  type="button"
                  onClick={() => onRender(s)}
                  disabled={payLocked}
                  aria-busy={busy || undefined}
                  className={RENDER_BTN}
                >
                  {busy ? <FiLoader className={SPIN} aria-hidden /> : <FiPlay aria-hidden />}
                  {t("studio_ui.render_scene")}
                </button>
              )}

              {/* Звук сцены: реплики героев, свой голос, музыка, эффекты. У не
                  снятой сцены звук копится и накладывается сам после съёмки. */}
              {onAudio && !working && (
                <button
                  type="button"
                  onClick={() => onAudio(s)}
                  disabled={busy}
                  className={vx(CS_CARD_BTN, Boolean(s.audio_count) && VS_PILL_ON)}
                >
                  <FiMic aria-hidden />
                  {s.audio_count
                    ? t("studio_ui.tl_audio_count", { defaultValue: "Звук · дорожек: {{n}}", n: s.audio_count })
                    : t("studio_ui.tl_audio", { defaultValue: "Звук: голос, музыка" })}
                </button>
              )}

              {/* С переносом: у «ошибки» с прежним роликом на телефоне здесь пять кнопок.
                  mt-auto — в сетке ряд значков стоит по низу карточки, как у соседей. */}
              <div className="mt-auto flex flex-wrap items-center gap-1.5 border-t border-vs-ink/10 pt-2.5">
                {/* Не disabled: стрелка гаснет, когда карточка доехала до края или ждёт
                    ответа, — и фокус с неё упал бы на страницу. */}
                <button
                  type="button"
                  onClick={() => {
                    if (i > 0 && !busy) onMove(s, -1);
                  }}
                  aria-disabled={i === 0 || busy || undefined}
                  aria-label={t("studio_ui.move_up")}
                  title={t("studio_ui.move_up")}
                  className={ROW_ICON}
                >
                  <FiArrowLeft aria-hidden />
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (i < scenes.length - 1 && !busy) onMove(s, 1);
                  }}
                  aria-disabled={i === scenes.length - 1 || busy || undefined}
                  aria-label={t("studio_ui.move_down")}
                  title={t("studio_ui.move_down")}
                  className={ROW_ICON}
                >
                  <FiArrowRight aria-hidden />
                </button>
                {s.status === "failed" && (
                  <button
                    type="button"
                    onClick={() => onRetry(s)}
                    disabled={payLocked}
                    aria-busy={busy || undefined}
                    // Кадр не трогаем: пересобираем только ролик, поэтому герой и
                    // композиция остаются прежними, а платим лишь за видео. Цена —
                    // прямо в подсказке. У готовой сцены — подписанная кнопка выше.
                    // Подписанная кнопка на любой ширине: это единственный повтор у
                    // такой строки, и отказ «нажмите ещё раз» указывает именно на неё.
                    title={`${t("studio_ui.retry_failed")}${
                      s.render_credits ? ` · ${s.render_credits} ${creditsShort}` : ""
                    }`}
                    className={vx(VS_BTN_GHOST, "!gap-1.5 !px-3 !text-[13px] md:!min-h-9")}
                  >
                    <FiRefreshCw className={busy ? SPIN : ""} aria-hidden />
                    {t("studio_ui.retry_failed_short", { defaultValue: DOCK_RU["studio_ui.retry_failed_short"] })}
                    {s.render_credits ? (
                      <span className="sr-only">{` · ${s.render_credits} ${creditsShort}`}</span>
                    ) : null}
                  </button>
                )}
                {/* Скачать отдельную сцену: клиент просил забирать не только
                    готовый мультфильм, но и каждый ролик по отдельности —
                    сцену часто выкладывают саму по себе. */}
                {s.video && (
                  <SaveMediaButton
                    url={s.video}
                    filename={`esai-scene-${s.order + 1}.mp4`}
                    label={t("studio_ui.download_scene")}
                    iconClassName=""
                    className={vx(ROW_ICON, "hover:!text-vs-accent")}
                  />
                )}
                {/* Снимающуюся сцену не удалить: ролик доснимется, а класть его
                    будет некуда (сервер тоже откажет). */}
                <button
                  type="button"
                  onClick={() => onDelete(s)}
                  disabled={busy || working}
                  aria-label={t("studio_ui.remove")}
                  title={
                    working
                      ? t("studio_ui.remove_working", {
                          defaultValue: "Сцена снимается — удалить можно после съёмки",
                        })
                      : t("studio_ui.remove")
                  }
                  className={vx(ROW_ICON, "ml-auto hover:!border-status-fail/40 hover:!text-status-fail")}
                >
                  <FiTrash2 aria-hidden />
                </button>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
