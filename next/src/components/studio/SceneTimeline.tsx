"use client";

import { useTranslation } from "react-i18next";
import SaveMediaButton from "@/components/ui/SaveMediaButton";
import {
  FiAlertTriangle,
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
} from "react-icons/fi";
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
}) {
  const { t } = useTranslation("common");
  const seconds = (n: number) => t("studio_ui.dock_seconds", { defaultValue: DOCK_RU["studio_ui.dock_seconds"], n });
  const cfgText = (c: SceneConfig) => [configLabel(c), seconds(c.duration)].filter(Boolean).join(" · ");

  if (!scenes.length) {
    return (
      <div className="rounded-2xl border border-dashed border-border p-6 text-center text-sm text-muted">
        {t("studio_ui.timeline_empty")}
      </div>
    );
  }

  return (
    <div className="flex gap-3 overflow-x-auto pb-2">
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
              ? `${s.shot.credits_planned} ${t("studio_ui.credits_short")}`
              : ""].filter(Boolean).join(" · ")
          : "";
        const note = notes?.[s.id];
        // Реплика длиннее сцены не уместится, а больше 300 знаков сервер не сохранит.
        const dialogueMax = dialogueMaxLength(s.preset.duration);
        return (
          <div
            key={s.id}
            className="flex w-56 shrink-0 flex-col gap-2 rounded-2xl border border-border bg-surface p-2.5"
          >
            <div className="flex items-center gap-1.5 text-[11px] text-muted-2">
              <span className="grid size-5 shrink-0 place-items-center rounded-full bg-accent text-[10px] font-bold text-on-accent">
                {i + 1}
              </span>
              <span className="truncate font-medium text-foreground">{s.preset.title}</span>
            </div>

            {/* Герой этой сцены. У черновика его можно сменить — так во второй
                сцене появляется другой персонаж, и история собирается из
                нескольких героев, а не одного. */}
            {s.character && (
              <div className="flex items-center gap-1.5">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={s.character.image}
                  alt=""
                  loading="lazy"
                  className="size-5 shrink-0 rounded-full object-cover"
                />
                <span className="truncate text-[11px] text-muted-2">{s.character.name}</span>
                {s.status === "draft" && characters.length > 1 && onPickCharacter && (
                  <select
                    value={s.character.id}
                    onChange={(e) => onPickCharacter(s, Number(e.target.value))}
                    title={t("studio_ui.scene_hero_change")}
                    className="ml-auto max-w-[7rem] shrink-0 rounded-md border border-border bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted outline-none focus:border-accent cursor-pointer"
                  >
                    {characters.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )}

            {/* Пропорции — как у будущего ролика: человек сразу видит, что
                получит в Reels или на YouTube. */}
            {/* Клиент: с вертикальным форматом карточка «поплыла» — кадр 9:16 во
                всю ширину занимал пол-экрана телефона, и лента переставала
                читаться. Высоту кадра ограничиваем: вертикальный и квадратный
                встают по центру в тех же пропорциях, карточка остаётся
                компактной, как была. */}
            <div className="flex justify-center rounded-xl bg-surface-2">
            <div
              className="relative overflow-hidden rounded-xl bg-surface-2"
              style={
                aspect === "16:9"
                  ? { aspectRatio: "16/9", width: "100%" }
                  : { aspectRatio: aspect.replace(":", "/"), height: "11rem" }
              }
            >
              {s.video ? (
                // Снятая сцена играет в ленте сама, без звука и по кругу
                // (клиент: лента сразу показывает героя, сцену и движение).
                // Звук и перемотка — через элементы управления плеера.
                <video
                  src={s.video}
                  controls
                  autoPlay
                  muted
                  loop
                  playsInline
                  preload="metadata"
                  poster={s.keyframe || undefined}
                  className="h-full w-full object-cover"
                />
              ) : s.preview_video && !working ? (
                <>
                  {/* Клиент: до съёмки человек должен видеть сцену с героем в
                      движении. Если эту пару уже снимали — показываем тот ролик,
                      он заранее готов и ничего не стоит. */}
                  <video
                    src={s.preview_video}
                    poster={s.keyframe || undefined}
                    autoPlay
                    muted
                    loop
                    playsInline
                    preload="metadata"
                    className="h-full w-full object-cover"
                  />
                  <span className="pointer-events-none absolute left-1.5 top-1.5 rounded-full bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white backdrop-blur-sm">
                    {t("studio_ui.preview_badge")}
                  </span>
                </>
              ) : s.custom_text && !s.keyframe && !working && s.status !== "failed" ? (
                <>
                  {/* Своя сцена до кадра: показать нечего, кроме замысла. Герой
                      и описание — ровно то, что пойдёт в съёмку. */}
                  <div className="flex h-full w-full flex-col justify-between gap-2 bg-gradient-to-br from-accent/15 via-surface-2 to-surface-2 p-2.5">
                    <p className="line-clamp-4 text-[11px] italic leading-snug text-foreground">
                      «{s.custom_text}»
                    </p>
                    {s.character && (
                      <span className="inline-flex w-fit items-center gap-1 rounded-full bg-black/40 py-0.5 pl-0.5 pr-2 text-[10px] text-white">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={s.character.image} alt="" className="size-4 rounded-full object-cover" />
                        {s.character.name}
                      </span>
                    )}
                  </div>
                </>
              ) : !s.keyframe && s.preset.clip && !working && s.status === "draft" ? (
                <>
                  {/* Ни ролика пары, ни кадра с героем. Раньше здесь в полный
                      кадр играло превью сцены — а оно снято с героем библиотеки,
                      и клиенту казалось, что выбранный герой «не поменялся».
                      Теперь сцена приглушена фоном, а крупно поверх — именно тот
                      герой, что закреплён за сценой. Увидеть его в самой сцене —
                      кнопкой «Примерить» ниже. */}
                  <video
                    src={s.preset.clip}
                    poster={s.preset.poster || undefined}
                    autoPlay
                    muted
                    loop
                    playsInline
                    preload="metadata"
                    className="h-full w-full scale-105 object-cover opacity-35 blur-[2px]"
                  />
                  {s.character && (
                    <span className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-1.5">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={s.character.image}
                        alt=""
                        className="h-[62%] aspect-square rounded-2xl object-cover shadow-lg ring-2 ring-accent/70"
                      />
                      <span className="rounded-full bg-black/60 px-2 py-0.5 text-[11px] font-medium text-white backdrop-blur-sm">
                        {s.character.name}
                      </span>
                    </span>
                  )}
                </>
              ) : s.keyframe || s.preset.poster ? (
                <>
                  {/* Пока своего кадра нет, показываем обложку сцены: у
                      черновика ничего не грузится, и крутилка на его месте
                      читалась как зависшая загрузка (жалоба клиента).
                      Кадр с героем чуть движется камерой — это не действие
                      героя, а живой предпросмотр, и подписан он честно. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={s.keyframe || s.preset.poster}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    className={`h-full w-full object-cover ${
                      s.keyframe ? (s.status === "draft" ? "studio-live" : "") : "opacity-70"
                    }`}
                  />
                  {s.keyframe && s.status === "draft" && (
                    <span className="pointer-events-none absolute left-1.5 top-1.5 rounded-full bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white backdrop-blur-sm">
                      {t("studio_ui.frame_badge")}
                    </span>
                  )}
                  {working && (
                    <span className="absolute inset-0 grid place-items-center bg-black/45 text-white">
                      <FiLoader className="animate-spin text-2xl" />
                    </span>
                  )}
                  {s.status === "failed" && (
                    <span className="absolute inset-0 grid place-items-center bg-black/45">
                      <FiAlertTriangle className="text-2xl text-red-400" />
                    </span>
                  )}
                </>
              ) : (
                <span className="grid h-full w-full place-items-center text-muted-2">
                  {s.status === "failed" ? (
                    <FiAlertTriangle className="text-2xl text-red-400" />
                  ) : working ? (
                    <FiLoader className="animate-spin text-2xl" />
                  ) : (
                    <FiFilm className="text-2xl" />
                  )}
                </span>
              )}
            </div>
            </div>

            <div className="flex items-center gap-1 text-[11px]">
              {s.status === "ready" ? (
                <span className="inline-flex items-center gap-1 text-emerald-400">
                  <FiCheck /> {t("studio_ui.st_ready")}
                </span>
              ) : s.status === "failed" ? (
                <span className="truncate text-status-fail">
                  {t("studio_ui.st_failed")}
                </span>
              ) : s.status === "draft" ? (
                // Чем снимется: модель и качество из дока (длительность — ниже, её можно выбрать).
                <span className="truncate text-muted-2">{configLabel(s.config)}</span>
              ) : (
                <span className="text-muted">{t(`studio_ui.${STATUS_KEY[s.status]}`)}…</span>
              )}
              {s.credits_spent > 0 && (
                <span className="ml-auto shrink-0 text-muted-2">{s.credits_spent} {t("studio_ui.credits_short")}</span>
              )}
            </div>

            {/* Чем снята или снимается сцена: снимок «Снять» — модель, качество, длительность. */}
            {shot && (working || s.status === "ready") && (
              <p className="truncate text-[11px] text-muted-2" title={shotText}>
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
              <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11px]">
                {choice && onDuration ? (
                  <label className="flex min-w-0 items-center gap-1 text-muted-2">
                    <FiClock className="shrink-0" aria-hidden />
                    <span className="sr-only">
                      {t("studio_ui.scene_duration", { defaultValue: DOCK_RU["studio_ui.scene_duration"] })}
                    </span>
                    <select
                      value={own == null ? "" : String(own)}
                      onChange={(e) => onDuration(s, e.target.value === "" ? null : Number(e.target.value))}
                      disabled={busy}
                      title={t("studio_ui.scene_duration", { defaultValue: DOCK_RU["studio_ui.scene_duration"] })}
                      className={`min-h-11 min-w-0 cursor-pointer rounded-lg border bg-surface-2 px-1.5 text-[11px] text-foreground outline-none transition-colors focus:border-accent focus-visible:ring-2 focus-visible:ring-accent/50 disabled:cursor-not-allowed disabled:opacity-60 md:min-h-8 ${
                        own != null ? "border-accent/60" : "border-border"
                      }`}
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
                  <span className="inline-flex items-center gap-1 text-muted-2">
                    <FiClock aria-hidden />
                    {seconds(current)}
                  </span>
                ) : null}
                {(s.status === "draft" || s.status === "failed") && (
                  <span className={`ml-auto shrink-0 tabular-nums ${noPrice ? "text-muted-2" : "font-semibold text-foreground"}`}>
                    {noPrice
                      ? t("studio_ui.price_unavailable", { defaultValue: "Цена сейчас недоступна" })
                      : rowCredits != null
                      ? `${rowCredits} ${t("studio_ui.credits_short")}`
                      : ""}
                  </span>
                )}
              </div>
            )}

            {/* Причина — текстом, а не подсказкой при наведении: на телефоне
                наведения нет, и человек видел одно «Не получилось». */}
            {s.status === "failed" && s.error && (
              <p className="line-clamp-4 text-[11px] leading-snug text-status-fail">{s.error}</p>
            )}

            {/* Ответ на то, что человек только что нажал у этой сцены («цена
                изменилась», «уже снята», «не сохранилось») — здесь, у кнопки, а не
                вверху страницы: с телефона тот блок не виден вовсе. role="alert" у обоих
                тонов: заметка появляется вместе с текстом, а такой role="status" многие
                чтецы не объявляют — «уже снята» не было бы слышно. Цвета — токены статусов:
                в светлой теме держат контраст 4.5:1. */}
            {note && (
              <div className="flex items-start gap-1">
                <p
                  role="alert"
                  className={`min-w-0 flex-1 text-[11px] leading-snug ${
                    note.tone === "error" ? "text-status-fail" : "text-status-wait"
                  }`}
                >
                  {note.text}
                </p>
                {onDismissNote && (
                  <button
                    type="button"
                    onClick={() => onDismissNote(s)}
                    aria-label={t("studio_ui.dock_hide_notice", { defaultValue: DOCK_RU["studio_ui.dock_hide_notice"] })}
                    className="-mr-1 -mt-1 grid size-11 shrink-0 cursor-pointer place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground md:size-7"
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
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[11px] text-muted transition-colors hover:border-accent hover:text-foreground disabled:opacity-60 cursor-pointer"
              >
                {tryingOnId === s.preset.id ? <FiLoader className="animate-spin" /> : <FiFilm />}
                {tryOnLabel || t("studio_ui.try_on")}
              </button>
            )}
            {s.status === "draft" && s.custom_text && !s.keyframe && onFrame && (
              <button
                type="button"
                onClick={() => onFrame(s)}
                disabled={busy || framingId !== null}
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[11px] text-muted transition-colors hover:border-accent hover:text-foreground disabled:opacity-60 cursor-pointer"
              >
                {framingId === s.id ? <FiLoader className="animate-spin" /> : <FiFilm />}
                {frameCredits != null
                  ? t("studio_ui.frame_btn", { credits: frameCredits })
                  : t("studio_ui.frame_btn_plain", { defaultValue: "Кадр" })}
              </button>
            )}
            {/* Реплика героя. Клиент: мультфильм должен смотреться как
                мультфильм — значит герой должен говорить, и говорить то, что
                задумал человек. Эта же строчка уходит в съёмку и в озвучку. */}
            {(s.status === "draft" || s.status === "ready" || s.status === "failed") && onDialogue && (
              <label className="flex flex-col gap-1">
                <span className="flex items-center justify-between text-[10px] uppercase tracking-wide text-muted-2">
                  {t("studio_ui.dialogue_label")}
                  <span className="normal-case tracking-normal">
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
                  className="rounded-lg border border-border bg-surface-2 px-2 py-1.5 text-[11px] text-foreground outline-none placeholder:text-muted-2 focus:border-accent"
                />
                {/* Клиент: «а нельзя, чтоб рот открывался?» Можно — но только
                    если реплику произносит сама модель при съёмке. */}
                <span className="text-[10px] leading-snug text-muted-2">
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
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-accent px-3 py-1.5 text-[11px] font-semibold text-accent transition-colors hover:bg-accent/10 disabled:opacity-60 cursor-pointer"
              >
                {busy ? <FiLoader className="animate-spin" /> : <FiRefreshCw />}
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
                title={t("studio_ui.retry")}
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[11px] font-semibold text-muted transition-colors hover:border-accent hover:text-foreground disabled:opacity-60 cursor-pointer"
              >
                <FiRefreshCw className={busy ? "animate-spin motion-reduce:animate-none" : ""} aria-hidden />
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
                className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[11px] text-muted transition-colors hover:border-accent hover:text-foreground disabled:opacity-60 cursor-pointer"
              >
                {busy || tryingOnId === s.preset.id || framingId === s.id ? (
                  <FiLoader className="animate-spin" />
                ) : (
                  <FiRefreshCw />
                )}
                {frameCredits != null
                  ? t("studio_ui.redraw_frame", { credits: frameCredits })
                  : t("studio_ui.redraw_frame_plain", { defaultValue: "🔄 Кадр заново" })}
              </button>
            )}
            {s.status === "draft" && (
              <button
                type="button"
                onClick={() => onRender(s)}
                disabled={payLocked}
                className="mb-1 inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-bold text-on-accent transition-colors hover:bg-accent-strong disabled:opacity-60 cursor-pointer"
              >
                {busy ? <FiLoader className="animate-spin" /> : <FiPlay />}
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
                className={`inline-flex w-full items-center justify-center gap-1.5 rounded-lg border px-3 py-1.5 text-[11px] font-semibold transition-colors disabled:opacity-60 cursor-pointer ${
                  s.audio_count
                    ? "border-accent/60 bg-accent/10 text-accent"
                    : "border-border text-muted hover:border-accent hover:text-foreground"
                }`}
              >
                <FiMic />
                {s.audio_count
                  ? t("studio_ui.audio_btn_count", { count: s.audio_count })
                  : t("studio_ui.audio_btn")}
              </button>
            )}

            {/* С переносом: у «ошибки» с прежним роликом на телефоне здесь пять кнопок. */}
            <div className="flex flex-wrap items-center gap-1">
              <button
                type="button"
                onClick={() => onMove(s, -1)}
                disabled={i === 0 || busy}
                title={t("studio_ui.move_up")}
                className="grid size-7 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground disabled:opacity-30 cursor-pointer"
              >
                <FiArrowLeft />
              </button>
              <button
                type="button"
                onClick={() => onMove(s, 1)}
                disabled={i === scenes.length - 1 || busy}
                title={t("studio_ui.move_down")}
                className="grid size-7 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground disabled:opacity-30 cursor-pointer"
              >
                <FiArrowRight />
              </button>
              {s.status === "failed" && (
                <button
                  type="button"
                  onClick={() => onRetry(s)}
                  disabled={payLocked}
                  // Кадр не трогаем: пересобираем только ролик, поэтому герой и
                  // композиция остаются прежними, а платим лишь за видео. Цена —
                  // прямо в подсказке. У готовой сцены — подписанная кнопка выше.
                  // На телефоне — 44 px и подпись: это единственный повтор у такой строки,
                  // и отказ «нажмите ещё раз» указывает именно на неё.
                  title={`${t("studio_ui.retry_failed")}${
                    s.render_credits ? ` · ${s.render_credits} ${t("studio_ui.credits_short")}` : ""
                  }`}
                  className="inline-flex h-11 shrink-0 cursor-pointer items-center justify-center gap-1 rounded-lg border border-border px-2.5 text-[11px] font-semibold text-muted transition-colors hover:bg-surface-2 hover:text-accent disabled:opacity-40 md:size-7 md:gap-0 md:border-0 md:px-0"
                >
                  <FiRefreshCw className={busy ? "animate-spin motion-reduce:animate-none" : ""} aria-hidden />
                  <span className="md:sr-only">
                    {t("studio_ui.retry_failed_short", { defaultValue: DOCK_RU["studio_ui.retry_failed_short"] })}
                  </span>
                  {s.render_credits ? (
                    <span className="sr-only">{` · ${s.render_credits} ${t("studio_ui.credits_short")}`}</span>
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
                  className="grid size-7 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-accent cursor-pointer"
                />
              )}
              {/* Снимающуюся сцену не удалить: ролик доснимется, а класть его
                  будет некуда (сервер тоже откажет). */}
              <button
                type="button"
                onClick={() => onDelete(s)}
                disabled={busy || working}
                title={
                  working
                    ? t("studio_ui.remove_working", {
                        defaultValue: "Сцена снимается — удалить можно после съёмки",
                      })
                    : t("studio_ui.remove")
                }
                className="ml-auto grid size-7 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-red-400 disabled:opacity-40 cursor-pointer"
              >
                <FiTrash2 />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
