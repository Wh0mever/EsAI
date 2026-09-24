"use client";

import { memo, useState, type Dispatch } from "react";
import { useTranslation } from "react-i18next";
import { FiImage, FiVideo } from "react-icons/fi";
import { cancelTake, trackVs } from "@/lib/vstudio/api";
import { errorText, reactionFor } from "@/lib/vstudio/errors";
import type { ModelJSON, ShotJSON, TakeLite, Uid, VsAction } from "@/lib/vstudio/types";
import CompiledDisclosure from "./CompiledDisclosure";
import InputsStrip from "./InputsStrip";
import ShotActions, { type ComposerFillReason } from "./ShotActions";
import TakeCarousel from "./TakeCarousel";
import TakeView from "./TakeView";
import {
  isLongPrompt,
  paramsSummary,
  pickTakeIndex,
  promptSegments,
  sameItems,
  shotDomId,
  type PromptSegment,
} from "./feedLogic";

export type ShotCardProps = {
  shot: ShotJSON;
  /** Дубли кадра по возрастанию (shotTakes). */
  takes: TakeLite[];
  /** Модель кадра в каталоге: null — её больше нет, undefined — каталог не загружен. */
  model: ModelJSON | null | undefined;
  /** ?take=<uid> или клик по тосту: этот дубль показать в карусели. */
  focusTake: Uid | null;
  /** Короткая подсветка карточки после прокрутки к ней. */
  highlighted: boolean;
  dispatch: Dispatch<VsAction>;
  onComposerFilled?: (reason: ComposerFillReason) => void;
};

type Tr = (k: string, o?: Record<string, unknown>) => string;

/** Текст чипа только для чтения: «@Image 2», «@Первый кадр», серый «@Image —», красный «@—». */
function chipText(t: Tr, seg: Extract<PromptSegment, { kind: "ref" }>): string {
  if (seg.state === "missing") return "@—";
  if (seg.state === "excluded") return "@Image —";
  if (seg.slot === "first_frame") return t("subject.first_frame", { defaultValue: "@Первый кадр" });
  if (seg.slot === "last_frame") return t("subject.last_frame", { defaultValue: "@Последний кадр" });
  return seg.n ? `@Image ${seg.n}` : "@Image —";
}

function chipAria(t: Tr, seg: Extract<PromptSegment, { kind: "ref" }>): string {
  if (seg.state === "missing") return t("shot.chipMissing", { defaultValue: "Фото удалено из запроса" });
  const base =
    seg.slot === "first_frame"
      ? t("inputs.firstFrame", { defaultValue: "Первый кадр" })
      : seg.slot === "last_frame"
        ? t("inputs.lastFrame", { defaultValue: "Последний кадр" })
        : seg.n
          ? t("tray.image", { defaultValue: "Фото {{n}}", n: seg.n })
          : t("tray.excluded", { defaultValue: "Не учитывается и не оплачивается" });
  return [base, seg.role].filter(Boolean).join(" · ");
}

/** Промпт кадра с чипами (только чтение). Длинный — свёрнут, но разворачивается целиком. */
function PromptView({ shot }: { shot: ShotJSON }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const tr = t as unknown as Tr;
  const [expanded, setExpanded] = useState(false);
  const blocks = promptSegments(shot);
  const long = isLongPrompt(shot.prompt_text);

  return (
    <div className="flex flex-col items-start gap-1">
      <div
        className={`w-full whitespace-pre-wrap break-words text-[15px] leading-relaxed text-foreground ${
          long && !expanded ? "line-clamp-5" : ""
        }`}
      >
        {blocks.map((block, bi) => (
          <span key={bi}>
            {bi > 0 && "\n"}
            {block.map((seg, si) =>
              seg.kind === "text" ? (
                <span key={si}>{seg.text}</span>
              ) : (
                <span
                  key={si}
                  role="img"
                  aria-label={chipAria(tr, seg)}
                  title={chipAria(tr, seg)}
                  className={`mx-px inline-flex translate-y-[-1px] items-center gap-1 whitespace-nowrap rounded-md px-1.5 align-baseline text-[13px] font-medium leading-6 ${
                    seg.state === "ok"
                      ? "bg-accent-soft text-foreground"
                      : seg.state === "excluded"
                        ? "bg-surface-3 text-muted-2 line-through"
                        : "bg-status-fail/15 text-status-fail"
                  }`}
                >
                  {seg.thumb && seg.state !== "missing" && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={seg.thumb} alt="" className="size-4 rounded-sm object-cover" loading="lazy" />
                  )}
                  {chipText(tr, seg)}
                </span>
              ),
            )}
          </span>
        ))}
      </div>
      {long && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="cursor-pointer rounded-md py-1 text-xs font-medium text-muted underline-offset-2 hover:text-foreground hover:underline"
        >
          {expanded
            ? t("run.actions.showLess", { defaultValue: "Свернуть" })
            : t("run.actions.showMore", { defaultValue: "Показать полностью" })}
        </button>
      )}
    </div>
  );
}

const LANG_TAG: Record<string, string> = { kg: "ky", ru: "ru", en: "en" };

function formatWhen(iso: string, lang: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  try {
    return new Intl.DateTimeFormat(LANG_TAG[lang] || lang || "ru", {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    }).format(d);
  } catch {
    return d.toISOString().slice(0, 16).replace("T", " ");
  }
}

/**
 * Карточка кадра в ленте (§9.2, §9.6): промпт с чипами, сводка параметров
 * «Seedance 2.0 · 9:16 · 10 с · 720p», миниатюры входов с «не учтено»,
 * карусель дублей, действия и «Что ушло модели».
 */
function ShotCard({ shot, takes, model, focusTake, highlighted, dispatch, onComposerFilled }: ShotCardProps) {
  const { t, i18n } = useTranslation("vstudio", { useSuspense: false });

  // Выбор в карусели: null — всегда последний (новый дубль после «Повторить» сразу виден).
  const [selected, setSelected] = useState<Uid | null>(null);
  const [seenCount, setSeenCount] = useState(takes.length);
  const [seenFocus, setSeenFocus] = useState<Uid | null>(null);
  const [canceling, setCanceling] = useState<Uid | null>(null);
  if (takes.length !== seenCount) {
    setSeenCount(takes.length);
    if (takes.length > seenCount) setSelected(null);
  }
  if (focusTake && focusTake !== seenFocus && takes.some((x) => x.uid === focusTake)) {
    setSeenFocus(focusTake);
    setSelected(focusTake);
  }

  const index = pickTakeIndex(takes, selected);
  const take = index >= 0 ? takes[index] : null;
  const summary = paramsSummary(shot, take);
  const video = shot.kind === "video";

  const parts: string[] = [];
  if (summary.model) parts.push(summary.model);
  else parts.push(t("shot.modelGone", { defaultValue: "Модель удалена" }));
  if (summary.aspect) {
    parts.push(summary.aspect === "auto" ? t("shot.aspectAuto", { defaultValue: "Авто" }) : summary.aspect);
  }
  if (summary.duration != null) parts.push(t("shot.seconds", { defaultValue: "{{n}} с", n: summary.duration }));
  if (summary.resolution) parts.push(summary.resolution);
  if (summary.audio === true) parts.push(t("shot.audio", { defaultValue: "со звуком" }));
  if (summary.audio === false) parts.push(t("shot.noAudio", { defaultValue: "без звука" }));

  const cancel = async (uid: Uid) => {
    if (canceling) return;
    setCanceling(uid);
    const res = await cancelTake(uid);
    setCanceling(null);
    if (res.ok) {
      dispatch({ type: "takes/upsert", takes: [res.data] });
      try {
        window.dispatchEvent(new CustomEvent("balance:refresh"));
      } catch {
        /* резерв в шапке обновится со следующим quote */
      }
      return;
    }
    const r = reactionFor(res.error);
    if (r.kind === "ignore") return;
    if (r.kind === "auth") {
      trackVs("vstudio_auth_prompt");
      dispatch({ type: "ui/auth", open: true });
      return;
    }
    // already_submitted: модель уже снимает — отменить нельзя, опрос покажет статус.
    dispatch({
      type: "ui/toast",
      toast: { id: `vs-cancel-${uid}`, tone: res.error.code === "already_submitted" ? "info" : "error", text: errorText(t, res.error) },
    });
  };

  return (
    <article
      id={shotDomId(shot.uid)}
      data-shot={shot.uid}
      aria-label={t("shot.aria", { defaultValue: "Запрос от {{when}}", when: formatWhen(shot.created_at, i18n.language) })}
      className={`flex scroll-mt-4 flex-col gap-3 rounded-2xl border bg-surface p-3 transition-shadow duration-500 sm:p-4 ${
        highlighted ? "border-accent shadow-[0_0_0_3px_var(--accent-soft)]" : "border-border"
      }`}
    >
      <PromptView shot={shot} />

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
        <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-foreground">
          {video ? <FiVideo aria-hidden /> : <FiImage aria-hidden />}
          {video ? t("kind.video", { defaultValue: "Видео" }) : t("kind.image", { defaultValue: "Картинка" })}
        </span>
        <span>{parts.join(" · ")}</span>
        <time dateTime={shot.created_at} className="ml-auto text-muted-2">
          {formatWhen(shot.created_at, i18n.language)}
        </time>
      </div>

      <InputsStrip inputs={shot.inputs} dropped={take?.dropped} culprit={take?.error?.input ?? null} />

      {take ? (
        <TakeCarousel takes={takes} index={index} onSelect={setSelected}>
          <TakeView
            take={take}
            inputs={shot.inputs}
            onCancel={() => void cancel(take.uid)}
            canceling={canceling === take.uid}
          />
        </TakeCarousel>
      ) : null}

      <ShotActions
        shot={shot}
        take={take}
        takes={takes}
        model={model}
        dispatch={dispatch}
        onComposerFilled={onComposerFilled}
      />

      {take && <CompiledDisclosure take={take} inputs={shot.inputs} />}
    </article>
  );
}

/** Опрос каждые 3 с меняет только открытые дубли — остальные карточки не перерисовываем. */
function sameProps(a: ShotCardProps, b: ShotCardProps): boolean {
  return (
    a.shot === b.shot &&
    sameItems(a.takes, b.takes) &&
    a.model === b.model &&
    a.highlighted === b.highlighted &&
    a.dispatch === b.dispatch &&
    a.onComposerFilled === b.onComposerFilled &&
    // focusTake важен только той карточке, чей это дубль.
    (a.focusTake === b.focusTake ||
      (!a.takes.some((x) => x.uid === a.focusTake) && !b.takes.some((x) => x.uid === b.focusTake)))
  );
}

export default memo(ShotCard, sameProps);
