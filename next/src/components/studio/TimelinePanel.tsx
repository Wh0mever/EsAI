"use client";

import { useId, type ReactNode, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import { FiLoader, FiMic, FiPlus } from "react-icons/fi";
import { VS_BTN_GHOST, VS_H2, VS_SECTION, VS_SUB, vx } from "@/components/vstudio/ui/skin";
import SceneTimeline, { type SceneNote, type StudioScene } from "./SceneTimeline";
import { CS_ANCHOR, CS_GAP, CS_HEAD, CS_NOTE_GOLD } from "./ui/cartoonSkin";
import FilmBlock from "./timeline/FilmBlock";
import type { Project, SceneHandlers, TimelineCharacter } from "./cartoonTypes";

export type TimelinePanelProps = {
  loading: boolean;
  authed: boolean;
  /** Лента видна: герой выбран или сцены уже есть. */
  show: boolean;
  project: Project | null;
  scenes: StudioScene[];
  /** Кого можно поставить на сцену. */
  characters: TimelineCharacter[];
  busyIds: Set<number>;
  repricing: boolean;
  framingId: number | null;
  frameCredits: number | undefined;
  tryingOn: number | null;
  /** Сообщения у строк; у гостя — нет. */
  notes: Record<number, SceneNote> | undefined;
  handlers: SceneHandlers;
  aspect: string;
  readyCount: number;
  drafts: number;
  working: boolean;
  voicingNow: boolean;
  total: { credits: number | null; count: number };
  audioEnabled: boolean;
  planning: boolean;
  /** Склейка идёт: запрос ушёл или мультфильм уже «собирается». */
  assembling: boolean;
  sectionRef: RefObject<HTMLDivElement | null>;
  onRename: (value: string) => void;
  onNewMovie: () => void;
  onAssemble: () => void;
  onVoiceAll: () => void;
  onGuestRender: () => void;
};

/**
 * Лента сцен мультфильма: шапка с прогрессом, карточки сцен, озвучка всего
 * мультфильма и заметки о съёмке.
 *
 * «Итого», «Собрать мультфильм» и «Снять мультфильм» гостя живут в доке внизу —
 * он виден на любой прокрутке; название мультфильма правится в шапке студии.
 * Секция стоит всегда, даже пустая: страница не прыгает, когда появляется
 * первая сцена, а прокрутке «к ленте» есть куда прийти.
 */
export default function TimelinePanel({
  loading,
  authed,
  show,
  project,
  scenes,
  characters,
  busyIds,
  repricing,
  framingId,
  frameCredits,
  tryingOn,
  notes,
  handlers,
  aspect,
  readyCount,
  drafts,
  working,
  voicingNow,
  audioEnabled,
  planning,
  sectionRef,
  onNewMovie,
  onVoiceAll,
}: TimelinePanelProps) {
  const { t } = useTranslation("common");
  const headingId = useId();
  const title = t("studio_ui.tl_title", { defaultValue: "Лента сцен" });

  const sub =
    authed && scenes.length > 0
      ? `${t("studio_ui.progress", { ready: readyCount, total: scenes.length })}${
          project && project.credits_spent > 0 ? t("studio_ui.spent", { count: project.credits_spent }) : ""
        }`
      : t("studio_ui.tl_sub", { defaultValue: "Сцены снимаются по одной, потом склеиваются в мультфильм" });

  // Низ секции: озвучка и короткие заметки о том, что сейчас происходит.
  const footer: ReactNode[] = [];
  // Клиент: «нажал — и весь мультфильм озвучен». Реплики пишет ИИ, цену
  // человек видит до запуска, в окне их можно поправить.
  if (authed && audioEnabled && scenes.length > 0) {
    footer.push(
      <button
        key="voice"
        type="button"
        onClick={() => onVoiceAll()}
        disabled={planning || voicingNow}
        aria-busy={planning || voicingNow || undefined}
        className={VS_BTN_GHOST}
      >
        {planning || voicingNow ? (
          <FiLoader className="animate-spin motion-reduce:animate-none" aria-hidden />
        ) : (
          <FiMic className="text-vs-accent" aria-hidden />
        )}
        {planning
          ? t("studio_ui.voiceall_planning")
          : voicingNow
          ? t("studio_ui.voiceall_progress", {
              done: project?.voicing?.done ?? 0,
              total: project?.voicing?.total ?? 0,
            })
          : t("studio_ui.voiceall_title")}
      </button>,
    );
  }
  // Озвучка оборвалась — человек должен понять, почему заговорили не все
  // сцены. Кредиты за неозвученное не списаны.
  if (authed && project?.voicing?.finished && project.voicing.error) {
    footer.push(
      <span key="voice-stopped" className="text-xs leading-snug text-status-wait">
        {t(
          project.voicing.error === "not_enough_credits"
            ? "studio_ui.voiceall_stopped_credits"
            : "studio_ui.voiceall_stopped",
          { done: project.voicing.done, total: project.voicing.total }
        )}
      </span>,
    );
  }
  if (authed && working) {
    footer.push(
      <span key="working" className="text-xs leading-snug text-muted">
        {t("studio_ui.working_note")}
      </span>,
    );
  }
  if (authed && drafts > 0) {
    footer.push(
      <span key="drafts" className="text-xs leading-snug text-muted-2">
        {t("studio_ui.drafts_hint", { count: drafts })}
      </span>,
    );
  }

  return (
    <section
      ref={sectionRef}
      aria-labelledby={headingId}
      aria-busy={loading || undefined}
      className={vx(VS_SECTION, CS_GAP, CS_ANCHOR)}
    >
      <div className={CS_HEAD}>
        <div className="min-w-0">
          {/* tabIndex -1: сюда ставится фокус после «К ленте сцен» и выбора мультфильма в списке. */}
          <h2 id={headingId} tabIndex={-1} className={vx(VS_H2, "outline-none")}>
            {title}
          </h2>
          <p className={vx(VS_SUB, "mt-1.5 max-w-xl tabular-nums")}>{sub}</p>
        </div>
        {authed && project && scenes.length > 0 && (
          <button type="button" onClick={() => onNewMovie()} className={VS_BTN_GHOST}>
            <FiPlus aria-hidden />
            {t("studio_ui.rail_new", { defaultValue: "Новый мультфильм" })}
          </button>
        )}
      </div>

      <div className="mt-4">
        {loading ? (
          // Та же высота, что у пустой ленты: когда данные придут, страница не прыгнет.
          <FilmBlock className="h-[136px] rounded-2xl sm:h-[116px]" />
        ) : (
          <SceneTimeline
            scenes={scenes}
            busyIds={busyIds}
            repricing={repricing}
            {...handlers}
            heroVoices={project?.hero_voices}
            characters={characters}
            framingId={framingId}
            frameCredits={frameCredits}
            aspect={aspect}
            tryingOnId={tryingOn}
            tryOnLabel={frameCredits != null ? t("studio_ui.try_on_price", { credits: frameCredits }) : undefined}
            notes={notes}
            label={title}
          />
        )}
      </div>

      {/* Гость дособрал ленту: сказать, что дальше, — сама кнопка «Снять
          мультфильм» в доке, рядом с «Итого». */}
      {!loading && !authed && show && scenes.length > 0 && (
        <div className={vx(CS_NOTE_GOLD, "mt-4")}>
          <p className="font-semibold">{t("studio_ui.guest_cta_title", { count: scenes.length })}</p>
          <p className="mt-0.5 text-xs text-muted">{t("studio_ui.guest_cta_note")}</p>
        </div>
      )}

      {!loading && footer.length > 0 && <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">{footer}</div>}
    </section>
  );
}
