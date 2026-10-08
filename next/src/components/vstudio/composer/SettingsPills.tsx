"use client";

/**
 * Видеостудия, панель запроса: параметры запуска чипами (с 768 px).
 *
 * Колонка параметров справа по умолчанию закрыта, поэтому главное стоит прямо
 * под полем запроса: «Видео | Картинка», модель, пропорции, длительность,
 * качество, звук. Чип открывает окошко с тем же пикером, что и в колонке, и с
 * теми же пропсами. Второго источника правды нет: значения читаются из стора,
 * меняются теми же действиями (selectKind, selectModel, composer/params), а
 * цена на кнопке «Создать» пересчитывается сама — её хук следит за стором.
 *
 * Параметр без выбора (у модели одно качество) — просто текст: чип, который
 * ничего не открывает, обманывал бы. Звук — переключатель без окошка.
 * На телефоне чипов нет: там SettingsChip и шторка параметров.
 */
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { FiChevronDown, FiImage, FiLock, FiRefreshCw, FiVideo, FiVolume2, FiVolumeX } from "react-icons/fi";
import { AspectShape, aspectHint } from "@/components/ui/AspectIcon";
import type { ShotParams, VsKind } from "@/lib/vstudio/types";
import { useVStudio } from "../context";
import { useVStudioModels } from "../hooks/useVStudioModels";
import AspectPicker from "../settings/AspectPicker";
import DurationPicker from "../settings/DurationPicker";
import ModelPicker, { MODEL_PICKER_EVENT } from "../settings/ModelPicker";
import ResolutionPicker from "../settings/ResolutionPicker";
import { openLockedModel } from "../settings/RunSettingsPanel";
import { VendorDot } from "../settings/SettingsBits";
import { AUTO, countInputs, findModel, forcedDuration, modelsFor, shownParams } from "../settings/settingsModel";
import { tx } from "../settings/settingsText";
import { selectKind, selectModel } from "../settings/useRunSettingsSync";
import { VS_FOCUS, VS_LABEL, VS_PILL, VS_PILL_ON, VS_SEG_THUMB, vx } from "../ui/skin";
import AnchoredPopover from "./Popover";

type PillKey = "model" | "aspect" | "duration" | "resolution";

const KINDS: { kind: VsKind; icon: typeof FiVideo; key: "kind.video" | "kind.image" }[] = [
  { kind: "video", icon: FiVideo, key: "kind.video" },
  { kind: "image", icon: FiImage, key: "kind.image" },
];

/** Чип параметра: плотнее общего VS_PILL — в строке их шесть, и рядом кнопка «Создать». */
const PILL = `${VS_PILL} !px-3 tabular-nums`;
const PILL_OPEN = "!border-vs-ink/25 !bg-vs-ink/[0.08] !text-foreground";
/** Значение, которого модель не умеет (пришло из «Изменить»): чип жёлтый, причина — в окошке. */
const PILL_WARN = "!border-status-wait/50 !text-status-wait";
/** Параметр без выбора: текст в рост чипа, без рамки и без нажатия. */
const PLAIN = "inline-flex h-9 shrink-0 items-center gap-1.5 px-1.5 text-[13px] font-medium tabular-nums text-muted";
/** Окошко пикера: ширина по сетке значений, поля как у разделов панели параметров. */
const SHEET = "p-3.5";

/** Строка чипов выше этого — значит, чипы перенеслись на вторую строку (чип 36 px, зазор 6 px). */
const ONE_ROW_MAX_PX = 52;
/** Сколько свободного места нужно, чтобы вернуть полные подписи после ужатия. */
const TIGHT_RELEASE_PX = 24;

const sameRes = (a: string, b: string | undefined) => typeof b === "string" && a.toLowerCase() === b.toLowerCase();

function PillButton({
  anchor,
  open,
  onToggle,
  name,
  value,
  title,
  warn,
  children,
}: {
  anchor: RefObject<HTMLButtonElement | null>;
  open: boolean;
  onToggle: () => void;
  /** Название параметра — для экранного диктора: «Пропорции: 16:9». */
  name: string;
  value: string;
  title?: string;
  warn?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      ref={anchor}
      type="button"
      onClick={onToggle}
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-label={`${name}: ${value}`}
      title={title || name}
      className={vx(PILL, warn && PILL_WARN, open && PILL_OPEN)}
    >
      {children}
    </button>
  );
}

function PlainValue({ name, title, children }: { name: string; title?: string; children: ReactNode }) {
  return (
    <span className={PLAIN} title={title || name}>
      <span className="sr-only">{name}: </span>
      {children}
    </span>
  );
}

export default function SettingsPills({ className }: { className?: string }) {
  const { t, i18n } = useTranslation("vstudio", { useSuspense: false });
  const tc = t as unknown as TFunction;
  const { state, dispatch, actions } = useVStudio();
  // Общий кэш моделей только читаем: перезапрашивает его контейнер студии.
  const { loading, error, reload } = useVStudioModels({ enabled: false });
  const { composer, models } = state;
  const { kind } = composer;

  const [open, setOpen] = useState<PillKey | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const modelRef = useRef<HTMLButtonElement | null>(null);
  const aspectRef = useRef<HTMLButtonElement | null>(null);
  const durationRef = useRef<HTMLButtonElement | null>(null);
  const resolutionRef = useRef<HTMLButtonElement | null>(null);

  // То же, что считает панель параметров (RunSettingsView), — чипы и колонка всегда показывают одно.
  const list = modelsFor(models, kind);
  const model = findModel(models, composer.model, kind);
  const counts = countInputs(composer.tray, composer.frames);
  const p = shownParams(model, kind, composer.params);
  const forced = forcedDuration(kind, model, counts);
  const video = kind === "video";

  const current = { kind: composer.kind, model: composer.model, params: composer.params };
  const onKind = (next: VsKind) => selectKind(dispatch, models, current, next);
  const onModel = (id: string) => selectModel(dispatch, models, current, id);
  const onParams = (patch: Partial<ShotParams>) => dispatch({ type: "composer/params", params: patch });

  /* ---------- что показывать ---------- */

  const aspects = model ? [...(model.caps.aspect_ratios || []), AUTO] : [];
  const aspect = p.aspect_ratio || AUTO;
  const aspectOff = Boolean(model) && !aspects.includes(aspect);
  const aspectFixed = aspects.length <= 1 && !aspectOff;
  const aspectText = aspect === AUTO ? tx(t, "settings.aspectAuto") : aspect;
  const aspectTitle =
    aspect === AUTO ? tx(t, video ? "settings.aspectAutoVideo" : "settings.aspectAutoImage") : aspectHint(tc, aspect);

  const durations = (video && model?.caps.durations) || [];
  const duration = forced ?? p.duration;
  const durationOff = forced == null && p.duration != null && !durations.includes(p.duration);
  const durationFixed = durations.length === 1 && !durationOff && forced == null;
  const durationText = duration != null ? tx(t, "settings.seconds", { n: duration }) : tx(t, "settings.duration");

  const resolutions = (video && model?.caps.resolutions) || [];
  const resolutionOff = Boolean(p.resolution) && !resolutions.some((r) => sameRes(r, p.resolution));
  const resolutionFixed = resolutions.length === 1 && !resolutionOff;
  const resolutionText = p.resolution || (resolutionFixed ? resolutions[0] : tx(t, "settings.resolution"));

  const audioSupported = Boolean(model?.caps.audio);
  const audioOn = audioSupported && p.generate_audio !== false;

  // Окошко живёт, только пока на месте его чип: сменили вид или модель — чипа может уже не быть.
  const can: Record<PillKey, boolean> = {
    model: Boolean(model),
    aspect: Boolean(model) && !aspectFixed,
    duration: Boolean(model) && durations.length > 0 && !durationFixed,
    resolution: Boolean(model) && resolutions.length > 0 && !resolutionFixed,
  };
  const shown = open && can[open] ? open : null;
  const refs: Record<PillKey, RefObject<HTMLButtonElement | null>> = {
    model: modelRef,
    aspect: aspectRef,
    duration: durationRef,
    resolution: resolutionRef,
  };

  const toggle = (key: PillKey) => setOpen((cur) => (cur === key ? null : key));
  /** Значение выбрано: окошко закрывается, фокус возвращается на чип. */
  const done = (key: PillKey) => {
    setOpen(null);
    refs[key].current?.focus();
  };

  /* ---------- «Другая модель» из ленты и из подсказок ---------- */

  useEffect(() => {
    const onOpen = () => {
      // Попросили из самой панели параметров (кнопка стоит в ней) — список раскроется там же.
      const from = document.activeElement;
      if (from instanceof HTMLElement && from.closest("aside, [aria-modal='true']")) return;
      // Модели ещё не пришли — чипа нет, открывать нечего.
      if (!modelRef.current) return;
      setOpen("model");
      // Зовущий по старой памяти открывает ещё и панель параметров; модель теперь
      // выбирают здесь, и выезжающая панель поверх окошка только мешала бы.
      dispatch({ type: "ui/panel", panel: "settings", open: false });
    };
    window.addEventListener(MODEL_PICKER_EVENT, onOpen);
    return () => window.removeEventListener(MODEL_PICKER_EVENT, onOpen);
  }, [dispatch]);

  /* ---------- чипы в одну строку ---------- */

  // Всё, от чего зависит ширина чипов: поменялось — перемерить.
  const fitKey = [kind, model?.id ?? "", model?.name ?? "", aspectText, durationText, resolutionText, forced ?? "", i18n.language].join("|");
  useLayoutEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    // Не помещаются в строку — сначала ужимаемся (у невыбранного вида остаётся значок) и только потом переносимся.
    const fit = () => {
      const wasTight = "tight" in el.dataset;
      delete el.dataset.tight;
      const wraps = el.offsetHeight > ONE_ROW_MAX_PX;
      // Обратно — только с запасом: у самой границы подпись иначе мигала бы на каждой смене «720p ↔ 1080p».
      const last = el.lastElementChild;
      const spare = last ? el.getBoundingClientRect().right - last.getBoundingClientRect().right : 0;
      if (wraps || (wasTight && spare < TIGHT_RELEASE_PX)) el.dataset.tight = "";
    };
    fit();
    if (typeof ResizeObserver === "undefined") return;
    let raf = 0;
    // Замер — в следующем кадре: менять вёрстку прямо в обработчике ResizeObserver нельзя, он зациклится.
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(fit);
    });
    ro.observe(el);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [fitKey]);

  /* ---------- раскладка ---------- */

  const kindSwitch = (
    <div
      role="group"
      aria-label={tx(t, "kind.label")}
      // В тёмной теме дорожка — как соседние чипы; в светлой — утопленная, с белой плашкой выбранного
      // (тот же вид, что у переключателя моделей на первом экране и в панели параметров).
      className="inline-flex shrink-0 items-center gap-0.5 rounded-full border border-vs-ink/10 bg-surface-3 p-0.5 dark:bg-vs-ink/[0.04]"
    >
      {KINDS.map(({ kind: k, icon: Icon, key }) => {
        // Вид без моделей не прячем, а выключаем: видно, что он есть, и почему нельзя.
        const empty = models ? modelsFor(models, k).length === 0 : false;
        const active = kind === k;
        const label = tx(t, key);
        return (
          <button
            key={k}
            type="button"
            aria-pressed={active}
            disabled={empty}
            title={empty ? `${label} · ${tx(t, "kind.soon")}` : label}
            onClick={() => {
              setOpen(null);
              onKind(k);
            }}
            className={vx(
              "inline-flex h-[30px] items-center gap-1.5 rounded-full px-2.5 text-[13px] font-medium transition-colors",
              VS_FOCUS,
              active ? vx(VS_SEG_THUMB, "text-vs-accent") : "text-muted",
              empty ? "cursor-not-allowed opacity-45" : "cursor-pointer",
              !active && !empty && "hover:text-foreground",
            )}
          >
            <Icon className="size-3.5 shrink-0" aria-hidden />
            <span className={active ? undefined : "group-data-[tight]/pills:sr-only"}>{label}</span>
          </button>
        );
      })}
    </div>
  );

  let modelPill: ReactNode;
  if (model) {
    modelPill = (
      <button
        ref={modelRef}
        type="button"
        onClick={() => toggle("model")}
        aria-haspopup="dialog"
        aria-expanded={shown === "model"}
        aria-label={`${tx(t, "settings.model")}: ${model.name}`}
        title={tx(t, "settings.modelChange")}
        className={vx(PILL, "!gap-2", shown === "model" && PILL_OPEN)}
      >
        <VendorDot modelId={model.id} />
        <span className="max-w-[9.5rem] truncate font-semibold text-foreground">{model.name}</span>
        {model.locked && <FiLock className="size-3 shrink-0 text-status-wait" aria-hidden />}
        <FiChevronDown
          className={vx("size-3.5 shrink-0 opacity-70 transition-transform duration-200 motion-reduce:transition-none", shown === "model" && "rotate-180")}
          aria-hidden
        />
      </button>
    );
  } else if (!list.length && error && !loading) {
    modelPill = (
      <button type="button" onClick={() => void reload()} title={tx(t, "settings.retry")} className={vx(PILL, PILL_WARN)}>
        <FiRefreshCw className="size-3.5 shrink-0" aria-hidden />
        {tx(t, "settings.modelsError")}
      </button>
    );
  } else if (models && !list.length && !loading) {
    modelPill = <span className={PLAIN}>{tx(t, "settings.modelsEmpty")}</span>;
  } else {
    modelPill = <span className="vs-film h-9 w-40 shrink-0 rounded-full" role="status" aria-label={tx(t, "settings.modelsLoading")} />;
  }

  return (
    <div ref={rootRef} role="group" aria-label={tx(t, "settings.title")} className={vx("group/pills flex flex-wrap items-center gap-1.5", className)}>
      {kindSwitch}
      {modelPill}

      {model &&
        (aspectFixed ? (
          <PlainValue name={tx(t, "settings.aspect")} title={aspectTitle}>
            <AspectShape ratio={aspect} size={16} className="shrink-0" />
            {aspectText}
          </PlainValue>
        ) : (
          <PillButton
            anchor={aspectRef}
            open={shown === "aspect"}
            onToggle={() => toggle("aspect")}
            name={tx(t, "settings.aspect")}
            value={aspectText}
            title={aspectTitle}
            warn={aspectOff}
          >
            <AspectShape ratio={aspect} size={16} className="shrink-0" />
            {aspectText}
          </PillButton>
        ))}

      {model &&
        durations.length > 0 &&
        (durationFixed ? (
          <PlainValue name={tx(t, "settings.duration")}>{durationText}</PlainValue>
        ) : (
          <PillButton
            anchor={durationRef}
            open={shown === "duration"}
            onToggle={() => toggle("duration")}
            name={tx(t, "settings.duration")}
            value={durationText}
            title={forced != null ? tx(t, "settings.durationForced", { model: model.name, n: forced }) : undefined}
            warn={durationOff}
          >
            {forced != null && <FiLock className="size-3 shrink-0 opacity-70" aria-hidden />}
            {durationText}
          </PillButton>
        ))}

      {model &&
        resolutions.length > 0 &&
        (resolutionFixed ? (
          <PlainValue
            name={tx(t, "settings.resolution")}
            title={tx(t, "settings.resolutionOnly", { model: model.name, res: resolutions[0] })}
          >
            {resolutionText}
          </PlainValue>
        ) : (
          <PillButton
            anchor={resolutionRef}
            open={shown === "resolution"}
            onToggle={() => toggle("resolution")}
            name={tx(t, "settings.resolution")}
            value={resolutionText}
            warn={resolutionOff}
          >
            {resolutionText}
          </PillButton>
        ))}

      {model && video && (
        // Подсказка — на обёртке: у выключенной кнопки браузер её не показывает.
        <span
          className="inline-flex shrink-0"
          title={
            audioSupported
              ? tx(t, audioOn ? "settings.audioHint" : "settings.audioOff")
              : tx(t, "settings.audioUnsupported", { model: model.name })
          }
        >
          <button
            type="button"
            role="switch"
            aria-checked={audioOn}
            aria-label={audioSupported ? tx(t, "settings.audio") : tx(t, "settings.audioUnsupported", { model: model.name })}
            disabled={!audioSupported}
            onClick={() => onParams({ generate_audio: !audioOn })}
            className={vx(VS_PILL, "w-9 justify-center !px-0", audioOn && VS_PILL_ON)}
          >
            {audioOn ? <FiVolume2 className="size-4" aria-hidden /> : <FiVolumeX className="size-4" aria-hidden />}
          </button>
        </span>
      )}

      {model && (
        <AnchoredPopover
          anchor={modelRef}
          open={shown === "model"}
          onClose={() => setOpen(null)}
          role="dialog"
          ariaLabel={tx(t, "settings.model")}
          autoFocus
          closeOnTabOut
        >
          <div className="flex w-[min(22.5rem,calc(100vw-1rem))] flex-col p-1.5">
            <div className={`${VS_LABEL} px-2 pb-2 pt-1.5`} aria-hidden>
              {tx(t, "settings.model")}
            </div>
            <ModelPicker
              inline
              kind={kind}
              models={list}
              value={model.id}
              counts={counts}
              onSelect={(id) => {
                onModel(id);
                done("model");
              }}
              onLocked={() => {
                // Окно тарифа (или входа) встаёт поверх: окошко со списком под ним не оставляем.
                setOpen(null);
                openLockedModel(dispatch, { requireAuth: actions.requireAuth });
              }}
              loading={loading || (!models && !error)}
              error={error}
              onRetry={() => void reload()}
            />
          </div>
        </AnchoredPopover>
      )}

      {model && (
        <AnchoredPopover
          anchor={aspectRef}
          open={shown === "aspect"}
          onClose={() => setOpen(null)}
          role="dialog"
          ariaLabel={tx(t, "settings.aspect")}
          autoFocus
          closeOnTabOut
        >
          <div className={`${SHEET} w-[min(20rem,calc(100vw-1rem))]`}>
            <AspectPicker
              kind={kind}
              model={model}
              value={p.aspect_ratio}
              onChange={(v) => {
                onParams({ aspect_ratio: v });
                done("aspect");
              }}
              duration={forced ?? p.duration}
              resolution={p.resolution}
            />
          </div>
        </AnchoredPopover>
      )}

      {model && video && (
        <AnchoredPopover
          anchor={durationRef}
          open={shown === "duration"}
          onClose={() => setOpen(null)}
          role="dialog"
          ariaLabel={tx(t, "settings.duration")}
          autoFocus
          closeOnTabOut
        >
          <div className={`${SHEET} w-[min(22rem,calc(100vw-1rem))]`}>
            <DurationPicker
              model={model}
              value={p.duration}
              onChange={(v) => {
                onParams({ duration: v });
                done("duration");
              }}
              resolution={p.resolution}
              aspect={p.aspect_ratio}
              forced={forced}
            />
          </div>
        </AnchoredPopover>
      )}

      {model && video && (
        <AnchoredPopover
          anchor={resolutionRef}
          open={shown === "resolution"}
          onClose={() => setOpen(null)}
          role="dialog"
          ariaLabel={tx(t, "settings.resolution")}
          autoFocus
          closeOnTabOut
        >
          <div className={`${SHEET} w-[min(18rem,calc(100vw-1rem))]`}>
            <ResolutionPicker
              model={model}
              value={p.resolution}
              onChange={(v) => {
                onParams({ resolution: v });
                done("resolution");
              }}
              duration={forced ?? p.duration}
              aspect={p.aspect_ratio}
            />
          </div>
        </AnchoredPopover>
      )}
    </div>
  );
}
