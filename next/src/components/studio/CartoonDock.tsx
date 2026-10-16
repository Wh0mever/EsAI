"use client";

/**
 * Мультстудия: нижний док «Модель / Качество / Длительность / Формат».
 *
 * Клиент (15.10.2026): по умолчанию Seedance 2.0 Mini в 480p — дешевле, но
 * модель, качество и длительность человек меняет сам. Док прилипает к низу
 * экрана, пока открыта студия, и садится на своё место над подвалом сайта —
 * поэтому последние сцены ленты он не закрывает навсегда.
 *
 * Пикеры — те же, что в видеостудии (ModelPicker, ResolutionPicker,
 * DurationPicker): они не зависят от её стора и берут модель в форме ModelJSON,
 * а цены в их таблицах — цены СЦЕНЫ (кадр + видео) в формате мультфильма. На
 * компьютере значение открывается окошком над кнопкой, на телефоне — шторкой.
 * Палитра студии (vs-*) живёт только внутри .vs-root: класс стоит на доке и на
 * окошках, которые рисуются порталом в body.
 */
import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { FiChevronDown, FiLoader, FiRefreshCw, FiX } from "react-icons/fi";
import { AspectShape, aspectHint } from "@/components/ui/AspectIcon";
import AnchoredPopover from "@/components/vstudio/composer/Popover";
import BottomSheet from "@/components/vstudio/BottomSheet";
import ModelPicker from "@/components/vstudio/settings/ModelPicker";
import ResolutionPicker from "@/components/vstudio/settings/ResolutionPicker";
import DurationPicker from "@/components/vstudio/settings/DurationPicker";
import { OptionButton, Reason, Section, VendorDot } from "@/components/vstudio/settings/SettingsBits";
import type { InputCounts } from "@/components/vstudio/settings/settingsModel";
import { VS_ICON_BTN, VS_LABEL, VS_PILL, vx } from "@/components/vstudio/ui/skin";
import {
  DOCK_RU,
  compactModelLabel,
  findModel,
  modelLabel,
  modelsForAspect,
  tablePrice,
  type CartoonModel,
  type DockNotice,
  type DockTextKey,
} from "./dockLogic";

type PillKey = "model" | "resolution" | "duration" | "aspect";

/** Сцена мультстудии не несёт своих фото: пикеру нечего сверять с материалами. */
const NO_INPUTS: InputCounts = { refs: 0, refsExcluded: 0, first: false, last: false, uploads: 0 };

/** Порядок форматов — как был над библиотекой: вертикаль первой (Reels, TikTok). */
const FORMATS = [
  { value: "9:16", key: "studio_ui.format_vertical", ru: "Reels, TikTok, Shorts" },
  { value: "16:9", key: "studio_ui.format_horizontal", ru: "YouTube, горизонтальное" },
  { value: "1:1", key: "studio_ui.format_square", ru: "Квадрат для ленты" },
] as const;

/** Сообщение «подогнали значение» висит столько, потом уходит само. */
const NOTICE_MS = 10_000;

/** На телефоне 44 px в высоту (правила студии) и уже по бокам — четыре кнопки встают в строку 360 px.
 *  Пока настройки сохраняются, кнопки «заняты» (aria-disabled, а не disabled — фокус остаётся на месте). */
const PILL = `${VS_PILL} !h-11 !px-2.5 tabular-nums md:!h-9 md:!px-3 aria-disabled:!cursor-progress aria-disabled:opacity-60`;
const PILL_OPEN = "!border-vs-ink/25 !bg-vs-ink/[0.08] !text-foreground";
/** Значение без выбора (у модели одно качество): текст в рост кнопки, без рамки и нажатия. */
const PLAIN = "inline-flex h-11 shrink-0 items-center gap-1.5 px-1.5 text-[13px] font-medium tabular-nums text-muted md:h-9";

const WIDE_QUERY = "(min-width: 768px)";

function subscribeWide(onChange: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {};
  const media = window.matchMedia(WIDE_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

/** С 768 px — окошко над кнопкой, уже — шторка снизу (как в видеостудии). */
function useWide(): boolean {
  return useSyncExternalStore(
    subscribeWide,
    () => typeof window.matchMedia === "function" && window.matchMedia(WIDE_QUERY).matches,
    () => true,
  );
}

export type DockValue = {
  /** OpenRouter id модели; null — неизвестна (пусто в библиотеке). */
  model: string | null;
  /** Подпись, если модели нет в списке дока (выключили): «Seedance 2.0». */
  modelName: string;
  resolution: string | null;
  duration: number | null;
  aspect: string;
};

export type CartoonDockProps = {
  /** null — список ещё грузится. */
  models: CartoonModel[] | null;
  modelsError: boolean;
  onRetryModels: () => void;
  value: DockValue;
  onModel: (id: string) => void;
  onResolution: (value: string) => void;
  onDuration: (value: number) => void;
  onAspect: (value: string) => void;
  notices: DockNotice[];
  onDismissNotices: () => void;
  /** Предупреждение, которое не уходит само (модель мультфильма выключили). */
  warning?: DockTextKey | null;
  /** «Итого»: сумма строк ленты, которые ещё снимать; credits null — цены нет. */
  total: { credits: number | null; count: number };
  /** В ленте есть снятые сцены — под форматом подсказка про поля при склейке. */
  hasShot: boolean;
  /** Цена кадра «типичной сцены» — для цен под форматами. */
  frameCredits?: number | null;
  /** Док или формат едут на сервер: кнопки заняты, пока не придёт ответ. */
  saving?: boolean;
  /** Отказ сервера на правку дока или формата — здесь, у кнопок, а не вверху страницы. */
  error?: string | null;
  onDismissError?: () => void;
};

/** Окошко пикера: над кнопкой на компьютере, шторка на телефоне. */
function PickerHost({
  wide,
  anchor,
  open,
  onClose,
  title,
  width,
  children,
}: {
  wide: boolean;
  anchor: RefObject<HTMLButtonElement | null>;
  open: boolean;
  onClose: () => void;
  title: string;
  /** Ширина окошка (Tailwind): у списка моделей шире, чем у сетки значений. */
  width: string;
  children: ReactNode;
}) {
  if (wide) {
    return (
      <AnchoredPopover
        anchor={anchor}
        open={open}
        onClose={onClose}
        role="dialog"
        ariaLabel={title}
        autoFocus
        closeOnTabOut
        className="vs-root"
      >
        <div className={width}>{children}</div>
      </AnchoredPopover>
    );
  }
  return (
    <BottomSheet open={open} onClose={onClose} title={title} className="vs-root" zIndex={1050}>
      {children}
    </BottomSheet>
  );
}

function FormatPicker({
  value,
  onChange,
  price,
  hasShot,
  t,
}: {
  value: string;
  onChange: (v: string) => void;
  price: (aspect: string) => number | null;
  hasShot: boolean;
  t: TFunction;
}) {
  const current = FORMATS.find((f) => f.value === value);
  return (
    <Section title={t("studio_ui.format_title", { defaultValue: "Формат видео" })}>
      <div className="grid grid-cols-3 gap-1.5">
        {FORMATS.map((f) => {
          const p = price(f.value);
          return (
            <OptionButton
              key={f.value}
              active={value === f.value}
              onClick={() => onChange(f.value)}
              icon={<AspectShape ratio={f.value} size={20} />}
              label={f.value}
              sub={p != null ? `${p} ${t("studio_ui.credits_short", { defaultValue: "кр" })}` : undefined}
              title={aspectHint(t, f.value)}
            />
          );
        })}
      </div>
      <Reason tone="muted">
        {current ? `${t(current.key, { defaultValue: current.ru })}. ` : ""}
        {t("studio_ui.dock_format_hint", { defaultValue: DOCK_RU["studio_ui.dock_format_hint"] })}
      </Reason>
      {hasShot && (
        <Reason>
          {t("studio_ui.format_note", {
            defaultValue: "Уже снятые сцены останутся в прежнем формате — при сборке они впишутся в общий кадр с полями.",
          })}
        </Reason>
      )}
    </Section>
  );
}

export default function CartoonDock({
  models,
  modelsError,
  onRetryModels,
  value,
  onModel,
  onResolution,
  onDuration,
  onAspect,
  notices,
  onDismissNotices,
  warning,
  total,
  hasShot,
  frameCredits,
  saving = false,
  error = null,
  onDismissError,
}: CartoonDockProps) {
  const { t } = useTranslation("common");
  const tf = t as unknown as TFunction;
  const d = (key: DockTextKey, params?: Record<string, string | number>) =>
    t(key, { defaultValue: DOCK_RU[key], ...(params || {}) });
  const wide = useWide();
  const [open, setOpen] = useState<PillKey | null>(null);
  // Какую кнопку тронули последней: пока сохраняется, крутилка — на ней. В конце
  // прокручиваемого ряда её на телефоне 360 px не было видно (уезжала за край).
  const [picked, setPicked] = useState<PillKey | null>(null);
  const modelRef = useRef<HTMLButtonElement | null>(null);
  const resolutionRef = useRef<HTMLButtonElement | null>(null);
  const durationRef = useRef<HTMLButtonElement | null>(null);
  const aspectRef = useRef<HTMLButtonElement | null>(null);
  const refs: Record<PillKey, RefObject<HTMLButtonElement | null>> = {
    model: modelRef,
    resolution: resolutionRef,
    duration: durationRef,
    aspect: aspectRef,
  };
  // position: sticky здесь не работает: у html и body сайта overflow-x: hidden, и
  // body становится своим «окном прокрутки». Поэтому — fixed, пока место дока в
  // конце студии не показалось на экране целиком.
  const slotRef = useRef<HTMLDivElement | null>(null);
  const barRef = useRef<HTMLDivElement | null>(null);
  const [docked, setDocked] = useState(false);
  const [barH, setBarH] = useState(0);

  useEffect(() => {
    const slot = slotRef.current;
    if (!slot || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([e]) => setDocked(Boolean(e) && e.intersectionRatio >= 0.99), {
      threshold: [0, 0.99, 1],
    });
    io.observe(slot);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    const bar = barRef.current;
    if (!bar || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setBarH(bar.offsetHeight));
    ro.observe(bar);
    return () => ro.disconnect();
  }, []);

  // Кнопка сайта «Наверх» (fixed, справа внизу) встаёт над доком, а не на него:
  // высоту дока она берёт из --esai-dock-h на <html> (BackToTop.tsx). Не только
  // пока док прилеплен: иначе в момент «посадки» кнопка прыгала бы вниз.
  useEffect(() => {
    const root = document.documentElement;
    if (barH) root.style.setProperty("--esai-dock-h", `${barH}px`);
    return () => {
      root.style.removeProperty("--esai-dock-h");
    };
  }, [barH]);

  // Сообщение «подогнали значение» уходит само: оно о только что сделанном
  // выборе, а сами значения и так видны на кнопках.
  useEffect(() => {
    if (!notices.length) return;
    const timer = window.setTimeout(onDismissNotices, NOTICE_MS);
    return () => window.clearTimeout(timer);
  }, [notices, onDismissNotices]);

  const aspect = value.aspect;
  // Таблицы цен — формата мультфильма: «от N кр» у квадрата ниже, чем у 16:9.
  const list = models ? modelsForAspect(models, aspect) : [];
  const model = findModel(list, value.model);
  const resolutions = model?.caps.resolutions || [];
  const durations = model?.caps.durations || [];
  const name = model ? modelLabel(model) : value.modelName;

  const can: Record<PillKey, boolean> = {
    model: list.length > 0,
    resolution: Boolean(model) && resolutions.length > 1,
    duration: Boolean(model) && durations.length > 1,
    aspect: true,
  };
  const shown = open && can[open] ? open : null;
  // Пока прежний выбор едет на сервер, новый не начинаем: иначе два PATCH разом и
  // на экране могло остаться не то, что сохранилось.
  const toggle = (key: PillKey) => {
    if (saving) return;
    setOpen((cur) => (cur === key ? null : key));
  };
  /** Занятость кнопки: видно (aria-disabled) и слышно (aria-busy). */
  const busy = saving ? ({ "aria-disabled": true, "aria-busy": true } as const) : {};
  /** Сохраняется именно эта кнопка; правка не отсюда — крутилка на первой, она всегда видна. */
  const spinning = (key: PillKey) => saving && (picked ?? "model") === key;
  /** Размер — как у значка, на место которого встаёт: кнопка не прыгает по ширине. */
  const spinner = (size = "size-3.5") => (
    <FiLoader className={vx(size, "shrink-0 animate-spin motion-reduce:animate-none")} aria-hidden />
  );
  /** Значение выбрано: окошко закрывается, фокус — обратно на кнопку. */
  const done = (key: PillKey) => {
    setPicked(key);
    setOpen(null);
    // Шторка возвращает фокус сама, окошку над кнопкой — помогаем.
    if (wide) refs[key].current?.focus();
  };

  const seconds = (n: number) => d("studio_ui.dock_seconds", { n });
  const credits = (n: number) => `${n} ${t("studio_ui.credits_short", { defaultValue: "кр" })}`;
  const resText = value.resolution || "—";
  const durText = value.duration != null ? seconds(value.duration) : "—";
  const formatPrice = (a: string) =>
    model ? tablePrice(model, { resolution: value.resolution, duration: value.duration, aspect: a }, frameCredits) : null;

  let modelPill: ReactNode;
  if (can.model) {
    modelPill = (
      <button
        ref={modelRef}
        type="button"
        onClick={() => toggle("model")}
        aria-haspopup="dialog"
        aria-expanded={shown === "model"}
        {...busy}
        aria-label={`${d("studio_ui.dock_model")}: ${name || "—"}`}
        title={d("studio_ui.dock_model")}
        className={vx(PILL, "!gap-2", shown === "model" && PILL_OPEN, warning && "!border-status-wait/50")}
      >
        <VendorDot modelId={value.model} />
        <span className="max-w-[6.5rem] truncate font-semibold text-foreground sm:hidden">{compactModelLabel(name || "—")}</span>
        <span className="hidden max-w-[10rem] truncate font-semibold text-foreground sm:inline">{name || "—"}</span>
        {spinning("model") ? (
          spinner()
        ) : (
          <FiChevronDown
            className={vx(
              "size-3.5 shrink-0 opacity-70 transition-transform duration-200 motion-reduce:transition-none",
              shown === "model" && "rotate-180",
            )}
            aria-hidden
          />
        )}
      </button>
    );
  } else if (modelsError) {
    modelPill = (
      <button type="button" onClick={onRetryModels} className={vx(PILL, "!border-status-wait/50 !text-status-wait")}>
        <FiRefreshCw className="size-3.5 shrink-0" aria-hidden />
        {d("studio_ui.dock_models_error")}
        <span className="sr-only">. {d("studio_ui.dock_retry")}</span>
      </button>
    );
  } else if (!models) {
    modelPill = <span className="vs-film h-11 w-28 shrink-0 rounded-full md:h-9" role="status" aria-label={d("studio_ui.dock_model")} />;
  } else {
    // Моделей в доке нет (ни одна не включена): сцены снимаются как в библиотеке.
    modelPill = name ? (
      <span className={PLAIN}>
        <span className="sr-only">{d("studio_ui.dock_model")}: </span>
        {name}
      </span>
    ) : null;
  }

  const valuePill = (key: "resolution" | "duration", label: string, text: string) =>
    can[key] ? (
      <button
        ref={refs[key]}
        type="button"
        onClick={() => toggle(key)}
        aria-haspopup="dialog"
        aria-expanded={shown === key}
        {...busy}
        aria-label={`${label}: ${text}`}
        title={label}
        className={vx(PILL, shown === key && PILL_OPEN)}
      >
        {text}
        {spinning(key) && spinner()}
      </button>
    ) : (key === "resolution" ? value.resolution : value.duration != null) ? (
      <span className={PLAIN} title={label}>
        <span className="sr-only">{label}: </span>
        {text}
      </span>
    ) : null;

  const formatTitle = t("studio_ui.format_title", { defaultValue: "Формат видео" });
  const hasNotes = Boolean(warning) || notices.length > 0;
  const closeBtn = vx(VS_ICON_BTN, "!size-11 md:!size-8");

  return (
    // Место дока в конце студии: пока оно не на экране, док прилеплен к низу окна
    // (fixed), а когда долистали — встаёт сюда и дальше уезжает вместе со
    // страницей, не закрывая подвал сайта. Высота места = высота дока: последние
    // сцены ленты док не закрывает. На телефоне — во всю ширину, как нижняя панель.
    <div ref={slotRef} className="mt-10" style={barH ? { minHeight: barH } : undefined}>
      <div ref={barRef} data-cartoon-dock="" className={docked ? "relative z-30 -mx-4" : "fixed inset-x-0 bottom-0 z-30"}>
        <div className="mx-auto w-full max-w-5xl sm:px-4 sm:pb-3">
          <div
            role="region"
            aria-label={d("studio_ui.dock_label")}
            // На телефоне фон панели уходит под полоску «домой» (safe area) — без щели снизу.
            className="vs-root vs-solid rounded-none !border-x-0 !border-b-0 pb-[env(safe-area-inset-bottom)] text-foreground sm:rounded-2xl sm:!border-x sm:!border-b sm:pb-0"
          >
            {/* Сообщения: область живая всегда, иначе диктор пропустил бы первое. */}
            <div role="status" aria-live="polite" className={hasNotes ? "flex items-start gap-2 border-b border-vs-ink/10 py-2 pl-3 pr-2" : "sr-only"}>
              {hasNotes && (
                <>
                  <div className="min-w-0 flex-1 space-y-0.5 py-0.5 text-[12px] leading-snug text-status-wait">
                    {warning && <p>{d(warning)}</p>}
                    {notices.map((n, i) => (
                      <p key={`${n.key}-${i}`}>{d(n.key, n.params)}</p>
                    ))}
                  </div>
                  {notices.length > 0 && (
                    <button
                      type="button"
                      onClick={onDismissNotices}
                      aria-label={d("studio_ui.dock_hide_notice")}
                      className={closeBtn}
                    >
                      <FiX className="size-4" aria-hidden />
                    </button>
                  )}
                </>
              )}
            </div>

            {/* Отказ сервера (не сохранилось, модель выключили) — прямо у кнопок, которые
                человек только что нажал: блок ошибки вверху страницы с телефона не виден. */}
            {error && (
              <div className="flex items-start gap-2 border-b border-vs-ink/10 py-2 pl-3 pr-2">
                <p role="alert" className="min-w-0 flex-1 py-0.5 text-[12px] leading-snug text-status-fail">
                  {error}
                </p>
                {onDismissError && (
                  <button type="button" onClick={onDismissError} aria-label={d("studio_ui.dock_hide_notice")} className={closeBtn}>
                    <FiX className="size-4" aria-hidden />
                  </button>
                )}
              </div>
            )}

            {/* Справа место под кнопкой «Наверх» сайта (fixed, 48 px справа внизу): над
                прилепленным доком она стоит сама, а мимо севшего на место дока проезжает при
                прокрутке — по полю, не по кнопкам. С 1280 px док уже, и кнопка стоит вне его. */}
            <div className="flex items-center gap-2 py-1.5 pl-3 pr-16 md:pr-[4.5rem] xl:pr-3">
              <div
                // Поля внутри прокрутки — чтобы кольцо фокуса у кнопок не срезалось.
                className="-my-1 flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto px-0.5 py-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
                aria-busy={saving || undefined}
              >
                {modelPill}
                {valuePill("resolution", d("studio_ui.dock_quality"), resText)}
                {valuePill("duration", d("studio_ui.dock_duration"), durText)}
                <button
                  ref={aspectRef}
                  type="button"
                  onClick={() => toggle("aspect")}
                  aria-haspopup="dialog"
                  aria-expanded={shown === "aspect"}
                  {...busy}
                  aria-label={`${formatTitle}: ${aspect}`}
                  title={aspectHint(tf, aspect)}
                  className={vx(PILL, shown === "aspect" && PILL_OPEN)}
                >
                  {spinning("aspect") ? spinner("size-4") : <AspectShape ratio={aspect} size={16} className="shrink-0" />}
                  {aspect}
                </button>
                {/* Крутилка — на самой кнопке (spinning), здесь только текст для чтеца. */}
                {saving && <span className="sr-only">{d("studio_ui.dock_saving")}</span>}
              </div>
              {total.count > 0 && (
                // На телефоне «Итого» — под лентой: в одну строку с четырьмя кнопками не помещается.
                <div className="hidden shrink-0 flex-col items-end leading-tight sm:flex" title={d("studio_ui.dock_total_title", { count: total.count })}>
                  <span className={VS_LABEL}>{d("studio_ui.dock_total")}</span>
                  <span className="text-sm font-semibold tabular-nums text-foreground">
                    {total.credits != null
                      ? credits(total.credits)
                      : t("studio_ui.price_unavailable", { defaultValue: "Цена сейчас недоступна" })}
                  </span>
                  <span className="sr-only">{d("studio_ui.dock_total_title", { count: total.count })}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {can.model && (
        <PickerHost
          wide={wide}
          anchor={modelRef}
          open={shown === "model"}
          onClose={() => setOpen(null)}
          title={d("studio_ui.dock_model")}
          width="flex w-[min(22.5rem,calc(100vw-1rem))] flex-col p-1.5"
        >
          {wide && (
            <div className={`${VS_LABEL} px-2 pb-2 pt-1.5`} aria-hidden>
              {d("studio_ui.dock_model")}
            </div>
          )}
          <ModelPicker
            inline
            kind="video"
            models={list}
            value={model?.id ?? null}
            counts={NO_INPUTS}
            onSelect={(id) => {
              onModel(id);
              done("model");
            }}
            // В мультстудии тарифного замка нет (locked всегда false).
            onLocked={() => setOpen(null)}
          />
        </PickerHost>
      )}

      {model && can.resolution && (
        <PickerHost
          wide={wide}
          anchor={resolutionRef}
          open={shown === "resolution"}
          onClose={() => setOpen(null)}
          title={d("studio_ui.dock_quality")}
          width="w-[min(18rem,calc(100vw-1rem))] p-3.5"
        >
          <ResolutionPicker
            model={model}
            value={value.resolution ?? undefined}
            onChange={(v) => {
              onResolution(v);
              done("resolution");
            }}
            duration={value.duration ?? undefined}
            aspect={aspect}
          />
        </PickerHost>
      )}

      {model && can.duration && (
        <PickerHost
          wide={wide}
          anchor={durationRef}
          open={shown === "duration"}
          onClose={() => setOpen(null)}
          title={d("studio_ui.dock_duration")}
          width="flex w-[min(22rem,calc(100vw-1rem))] flex-col gap-2.5 p-3.5"
        >
          <DurationPicker
            model={model}
            value={value.duration ?? undefined}
            onChange={(v) => {
              onDuration(v);
              done("duration");
            }}
            resolution={value.resolution ?? undefined}
            aspect={aspect}
          />
          <Reason tone="muted">{d("studio_ui.dock_duration_hint")}</Reason>
        </PickerHost>
      )}

      <PickerHost
        wide={wide}
        anchor={aspectRef}
        open={shown === "aspect"}
        onClose={() => setOpen(null)}
        title={formatTitle}
        width="w-[min(20rem,calc(100vw-1rem))] p-3.5"
      >
        <FormatPicker
          value={aspect}
          onChange={(v) => {
            onAspect(v);
            done("aspect");
          }}
          price={formatPrice}
          hasShot={hasShot}
          t={tf}
        />
      </PickerHost>
    </div>
  );
}
