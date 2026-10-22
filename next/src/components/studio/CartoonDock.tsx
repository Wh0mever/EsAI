"use client";

/**
 * Мультстудия: нижний док «Модель / Качество / Длительность / Формат», сумма
 * сцен к съёмке и главная кнопка — как панель запроса видеостудии.
 *
 * Клиент (15.10.2026): по умолчанию Seedance 2.0 Mini в 480p — дешевле, но
 * модель, качество и длительность человек меняет сам. Док стоит внизу оболочки
 * студии (VStudioShell, слот composer) и виден на любой прокрутке; место и
 * отступ от «домой» на телефоне даёт оболочка.
 *
 * Главная кнопка — только то, что на сайте уже есть (BUILD_D, решение 5):
 * «Собрать мультфильм», а гостю — «Снять мультфильм», то есть вход. «Снять все»
 * есть лишь в боте, здесь его нет.
 *
 * Пикеры — те же, что в видеостудии (ModelPicker, ResolutionPicker,
 * DurationPicker): они не зависят от её стора и берут модель в форме ModelJSON,
 * а цены в их таблицах — цены СЦЕНЫ (кадр + видео) в формате мультфильма. С
 * 768 px у каждого значения своя кнопка; любая открывает одно окошко над доком со
 * всеми четырьмя пикерами и сразу показывает свой раздел. На телефоне док — одна
 * строка, как у видеостудии: кнопка-сводка «2.0 Mini · 480p · 5 с · 16:9»
 * (SettingsChip) открывает шторку с теми же пикерами, рядом сумма и главная кнопка.
 *
 * Клиент (22.10.2026): окно не закрывается после каждого выбора — как «Параметры»
 * видеостудии, характеристики выбираются подряд до «Готово». Пока выбор едет на
 * сервер, пикеры на миг заняты: второй PATCH поверх первого не уходит.
 *
 * Палитра студии (vs-*) живёт только внутри .vs-root: класс стоит на доке и на
 * окошках, которые рисуются порталом в body.
 */
import { useEffect, useId, useRef, useState, useSyncExternalStore, type ReactNode, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { FiChevronDown, FiFilm, FiLoader, FiRefreshCw, FiX } from "react-icons/fi";
import { AspectShape, aspectHint } from "@/components/ui/AspectIcon";
import AnchoredPopover from "@/components/vstudio/composer/Popover";
import BottomSheet from "@/components/vstudio/BottomSheet";
import { EDGE_FADE, useEdgeFade } from "@/components/vstudio/home/strip/useEdgeFade";
import ModelPicker, { openModelPicker } from "@/components/vstudio/settings/ModelPicker";
import ResolutionPicker from "@/components/vstudio/settings/ResolutionPicker";
import DurationPicker from "@/components/vstudio/settings/DurationPicker";
import { OptionButton, Reason, Section, VendorDot } from "@/components/vstudio/settings/SettingsBits";
import type { InputCounts } from "@/components/vstudio/settings/settingsModel";
import { VS_BTN_GHOST, VS_FOCUS, VS_ICON_BTN, VS_LABEL, VS_PILL, vx } from "@/components/vstudio/ui/skin";
import { CS_RUN_GOLD, CS_RUN_OFF } from "./ui/cartoonSkin";
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
import type { DockPrimary, DockValue } from "./cartoonTypes";

type PillKey = "model" | "resolution" | "duration" | "aspect";
/**
 * Окно параметров открыто: from — какой кнопкой (его раздел показываем первым и
 * туда возвращаем фокус); null — сводкой на телефоне.
 */
type OpenState = { from: PillKey | null };

/** Сцена мультстудии не несёт своих фото: пикеру нечего сверять с материалами. */
const NO_INPUTS: InputCounts = { refs: 0, refsExcluded: 0, first: false, last: false, uploads: 0 };

/** Порядок форматов — как был над библиотекой: вертикаль первой (Reels, TikTok). */
const FORMATS = [
  { value: "9:16", key: "studio_ui.format_vertical", ru: "Reels, TikTok, Shorts" },
  { value: "16:9", key: "studio_ui.format_horizontal", ru: "YouTube, горизонтальное" },
  { value: "1:1", key: "studio_ui.format_square", ru: "Квадрат для ленты" },
] as const;

/** Сообщение «подогнали значение» и подсказка у выключенной кнопки висят столько, потом уходят сами. */
const NOTICE_MS = 10_000;
const HINT_MS = 6_000;

/** Кнопки значений (с 768 px). Пока док занят, кнопки «заняты» (aria-disabled, а не disabled — фокус остаётся на месте). */
const PILL = `${VS_PILL} !px-3 tabular-nums aria-disabled:!cursor-progress aria-disabled:opacity-60`;
const PILL_OPEN = "!border-vs-ink/25 !bg-vs-ink/[0.08] !text-foreground";
/** Телефон: сводка параметров во всю свободную ширину строки, 44 px в высоту; длинная — обрезается, а не раздвигает строку. */
const CHIP = vx(PILL, "!h-11 min-w-0 flex-1 justify-start !gap-2 overflow-hidden");
/** Значение без выбора (у модели одно качество): текст в рост кнопки, без рамки и нажатия. */
const PLAIN = "inline-flex h-9 shrink-0 items-center gap-1.5 px-1.5 text-[13px] font-medium tabular-nums text-muted";
/** Сумма сцен к съёмке: подпись и сумма столбиком справа, перед главной кнопкой. */
const TOTAL = "flex min-h-11 min-w-0 shrink-0 flex-col items-end justify-center rounded-xl px-1.5 text-right leading-tight md:px-2";
/** Подпись суммы: на телефоне строчными — заглавные не помещались в строку с кнопками. */
const TOTAL_LABEL = vx(VS_LABEL, "max-md:font-medium max-md:normal-case max-md:tracking-normal");

const WIDE_QUERY = "(min-width: 768px)";

function subscribeWide(onChange: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {};
  const media = window.matchMedia(WIDE_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

/** С 768 px — кнопки значений и окошки над ними, уже — сводка и шторка (как в видеостудии). */
function useWide(): boolean {
  return useSyncExternalStore(
    subscribeWide,
    () => typeof window.matchMedia === "function" && window.matchMedia(WIDE_QUERY).matches,
    () => true,
  );
}

export type { DockValue } from "./cartoonTypes";

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
  /** Сумма строк ленты, которые ещё снимать; credits null — цены нет. */
  total: { credits: number | null; count: number };
  /** В ленте есть снятые сцены — под форматом подсказка про поля при склейке. */
  hasShot: boolean;
  /** Цена кадра «типичной сцены» — для цен под форматами. */
  frameCredits?: number | null;
  /** Док или формат едут на сервер: кнопки заняты, пока не придёт ответ. */
  saving?: boolean;
  /**
   * Студия ещё грузится: док виден, но не нажимается. Мультфильма и черновика
   * пока нет, и любой выбор лёг бы в пустой черновик гостя поверх сохранённого.
   */
  disabled?: boolean;
  /** Отказ сервера на правку дока или формата — здесь, у кнопок, а не вверху страницы. */
  error?: string | null;
  onDismissError?: () => void;
  /** Главная кнопка дока: «Собрать мультфильм» или вход гостя; null — кнопки нет. */
  primary?: DockPrimary | null;
  /** Нажали сумму — показать ленту сцен. */
  onTotal?: () => void;
};

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
  disabled = false,
  error = null,
  onDismissError,
  primary = null,
  onTotal,
}: CartoonDockProps) {
  const { t } = useTranslation("common");
  const tf = t as unknown as TFunction;
  const d = (key: DockTextKey, params?: Record<string, string | number>) =>
    t(key, { defaultValue: DOCK_RU[key], ...(params || {}) });
  const wide = useWide();
  const [open, setOpen] = useState<OpenState | null>(null);
  // Какую кнопку тронули последней: пока сохраняется, крутилка — на ней. В конце
  // прокручиваемого ряда её на узком экране не было видно (уезжала за край).
  const [picked, setPicked] = useState<PillKey | null>(null);
  // Нажали выключенную «Собрать мультфильм» на телефоне: причина показывается строкой под доком.
  const [hint, setHint] = useState(false);
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
  // Ряд кнопок значений — якорь окна параметров: нажатие на соседнюю кнопку его не закрывает.
  const pillsRowRef = useRef<HTMLDivElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const reasonId = useId();
  const { attach: pillsRef, fade: pillsFade } = useEdgeFade<HTMLDivElement>();

  // Сообщение «подогнали значение» уходит само: оно о только что сделанном
  // выборе, а сами значения и так видны на кнопках.
  useEffect(() => {
    if (!notices.length) return;
    const timer = window.setTimeout(onDismissNotices, NOTICE_MS);
    return () => window.clearTimeout(timer);
  }, [notices, onDismissNotices]);

  useEffect(() => {
    if (!hint) return;
    const timer = window.setTimeout(() => setHint(false), HINT_MS);
    return () => window.clearTimeout(timer);
  }, [hint]);

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
  // Окно одно: с 768 px — окошко над кнопками, уже — шторка.
  const isOpen = open !== null;
  const from = open?.from ?? null;
  /** Окно открыто этой кнопкой: она подсвечена, как нажатая. */
  const openedBy = (key: PillKey) => isOpen && from === key;
  // Занят — сохраняется прежний выбор или студия ещё не загрузилась.
  const locked = saving || disabled;
  /**
   * Кнопка значения: открыть окно на её разделе; повторное нажатие — закрыть.
   * При открытом окне другая кнопка только переводит к своему разделу.
   */
  const toggle = (key: PillKey | null) => {
    if (isOpen && from === key) {
      closePanel();
      return;
    }
    if (locked && !isOpen) return;
    if (isOpen && key === "model") openModelPicker();
    setOpen({ from: key });
  };
  /** «Готово», Esc, клик мимо: окно закрывается, фокус — на кнопку, которой открыли. */
  const closePanel = () => {
    const back = from ?? "model";
    setOpen(null);
    // Шторка возвращает фокус сама; окошку над кнопками — помогаем, если фокус
    // не ушёл туда, куда человек нажал мимо окна.
    if (!wide) return;
    requestAnimationFrame(() => {
      const at = document.activeElement;
      if (at && at !== document.body) return;
      refs[back].current?.focus();
    });
  };

  // Окно открыли кнопкой значения (или перешли к другой): показать её раздел и
  // поставить фокус на выбранное значение.
  useEffect(() => {
    if (!isOpen || !wide) return;
    let raf = requestAnimationFrame(() => {
      raf = requestAnimationFrame(() => {
        const part = panelRef.current?.querySelector<HTMLElement>(`[data-dock-part="${from ?? "model"}"]`);
        if (!part) return;
        part.scrollIntoView({ block: "nearest" });
        const target =
          part.querySelector<HTMLElement>('button[aria-pressed="true"]:not([disabled])') ??
          part.querySelector<HTMLElement>("button:not([disabled])");
        target?.focus({ preventScroll: true });
      });
    });
    return () => cancelAnimationFrame(raf);
  }, [isOpen, wide, from]);

  /** Занятость кнопки: видно (aria-disabled) и слышно (aria-busy). */
  const busy = locked ? ({ "aria-disabled": true, "aria-busy": true } as const) : {};
  /** Сохраняется именно эта кнопка; правка не отсюда — крутилка на первой, она всегда видна. */
  const spinning = (key: PillKey) => saving && (picked ?? "model") === key;
  /** Размер — как у значка, на место которого встаёт: кнопка не прыгает по ширине. */
  const spinner = (size = "size-3.5") => (
    <FiLoader className={vx(size, "shrink-0 animate-spin motion-reduce:animate-none")} aria-hidden />
  );
  /**
   * Выбор в окне: окно остаётся открытым (следующую характеристику выбирают
   * сразу), крутилка встаёт на кнопку этого значения. Пока прежний выбор едет на
   * сервер, новый не принимаем: иначе два PATCH разом и на экране могло остаться
   * не то, что сохранилось.
   */
  const choose =
    <T,>(key: PillKey, apply: (value: T) => void) =>
    (value: T) => {
      if (locked) return;
      setPicked(key);
      apply(value);
    };

  const seconds = (n: number) => d("studio_ui.dock_seconds", { n });
  const credits = (n: number) => `${n} ${t("studio_ui.credits_short", { defaultValue: "кр" })}`;
  const resText = value.resolution || "—";
  const durText = value.duration != null ? seconds(value.duration) : "—";
  const formatPrice = (a: string) =>
    model ? tablePrice(model, { resolution: value.resolution, duration: value.duration, aspect: a }, frameCredits) : null;

  const formatTitle = t("studio_ui.format_title", { defaultValue: "Формат видео" });
  const hasNotes = Boolean(warning) || notices.length > 0;
  const closeBtn = vx(VS_ICON_BTN, "!size-11 md:!size-8");

  // С 768 px: своя кнопка у каждого значения.
  let modelPill: ReactNode = null;
  if (can.model) {
    modelPill = (
      <button
        ref={modelRef}
        type="button"
        onClick={() => toggle("model")}
        aria-haspopup="dialog"
        aria-expanded={openedBy("model")}
        {...busy}
        aria-label={`${d("studio_ui.dock_model")}: ${name || "—"}`}
        title={d("studio_ui.dock_model")}
        className={vx(PILL, "!gap-2", openedBy("model") && PILL_OPEN, warning && "!border-status-wait/50")}
      >
        <VendorDot modelId={value.model} />
        <span className="max-w-[10rem] truncate font-semibold text-foreground">{name || "—"}</span>
        {spinning("model") ? (
          spinner()
        ) : (
          <FiChevronDown
            className={vx(
              "size-3.5 shrink-0 opacity-70 transition-transform duration-200 motion-reduce:transition-none",
              openedBy("model") && "rotate-180",
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
    modelPill = <span className="vs-film h-9 w-28 shrink-0 rounded-full" role="status" aria-label={d("studio_ui.dock_model")} />;
  } else if (name) {
    // Моделей в доке нет (ни одна не включена): сцены снимаются как в библиотеке.
    modelPill = (
      <span className={PLAIN}>
        <span className="sr-only">{d("studio_ui.dock_model")}: </span>
        {name}
      </span>
    );
  }

  const valuePill = (key: "resolution" | "duration", label: string, text: string) =>
    can[key] ? (
      <button
        ref={refs[key]}
        type="button"
        onClick={() => toggle(key)}
        aria-haspopup="dialog"
        aria-expanded={openedBy(key)}
        {...busy}
        aria-label={`${label}: ${text}`}
        title={label}
        className={vx(PILL, openedBy(key) && PILL_OPEN)}
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

  const aspectPill = (
    <button
      ref={aspectRef}
      type="button"
      onClick={() => toggle("aspect")}
      aria-haspopup="dialog"
      aria-expanded={openedBy("aspect")}
      {...busy}
      aria-label={`${formatTitle}: ${aspect}`}
      title={aspectHint(tf, aspect)}
      className={vx(PILL, openedBy("aspect") && PILL_OPEN)}
    >
      {spinning("aspect") ? spinner("size-4") : <AspectShape ratio={aspect} size={16} className="shrink-0" />}
      {aspect}
    </button>
  );

  // Телефон: одна сводка параметров и шторка.
  const summaryParts = [
    modelsError && !can.model ? d("studio_ui.dock_models_error") : name ? compactModelLabel(name) : "",
    value.resolution || "",
    value.duration != null ? seconds(value.duration) : "",
    aspect,
  ].filter(Boolean);
  const summary = summaryParts.join(" · ");
  // Пока модели не пришли, сводке нечего сказать, кроме формата: вместо неё — «плёнка», как у видеостудии.
  const summaryPending = !models && !modelsError;
  const chip = (
    <button
      type="button"
      onClick={() => toggle(null)}
      aria-haspopup="dialog"
      aria-expanded={isOpen}
      {...busy}
      aria-label={`${d("studio_ui.dock_label")}: ${summary}`}
      title={summary}
      className={vx(
        CHIP,
        isOpen && PILL_OPEN,
        (warning || (modelsError && !can.model)) && "!border-status-wait/50",
      )}
    >
      {modelsError && !can.model ? (
        <FiRefreshCw className="size-3.5 shrink-0 text-status-wait" aria-hidden />
      ) : (
        <VendorDot modelId={value.model} />
      )}
      {summaryPending ? (
        <span className="vs-film h-2.5 w-24 min-w-0 rounded-full" aria-hidden />
      ) : (
        <span className="min-w-0 truncate font-semibold text-foreground">{summary}</span>
      )}
      {saving ? (
        <span className="ml-auto flex shrink-0">{spinner()}</span>
      ) : (
        <FiChevronDown className="ml-auto size-3.5 shrink-0 opacity-70" aria-hidden />
      )}
    </button>
  );

  // Пикеры — одни и те же в окошке над кнопками (с 768 px) и в шторке (телефон).
  const resolutionPicker =
    model && can.resolution ? (
      <ResolutionPicker
        model={model}
        value={value.resolution ?? undefined}
        onChange={choose("resolution", onResolution)}
        duration={value.duration ?? undefined}
        aspect={aspect}
      />
    ) : null;
  const durationPicker =
    model && can.duration ? (
      <>
        <DurationPicker
          model={model}
          value={value.duration ?? undefined}
          onChange={choose("duration", onDuration)}
          resolution={value.resolution ?? undefined}
          aspect={aspect}
        />
        <Reason tone="muted">{d("studio_ui.dock_duration_hint")}</Reason>
      </>
    ) : null;
  const formatPicker = (
    <FormatPicker
      value={aspect}
      onChange={choose("aspect", onAspect)}
      price={formatPrice}
      hasShot={hasShot}
      t={tf}
    />
  );

  let modelSection: ReactNode = null;
  if (can.model) {
    modelSection = (
      <ModelPicker
        kind="video"
        models={list}
        value={model?.id ?? null}
        counts={NO_INPUTS}
        onSelect={choose("model", onModel)}
        // Открыли кнопкой модели — список уже раскрыт (окно монтируется заново при каждом открытии).
        defaultOpen={from === "model"}
        // В мультстудии тарифного замка нет (locked всегда false).
        onLocked={closePanel}
      />
    );
  } else if (modelsError) {
    modelSection = (
      <Section title={d("studio_ui.dock_model")}>
        <Reason tone="warn">{d("studio_ui.dock_models_error")}</Reason>
        <button type="button" onClick={onRetryModels} className={vx(VS_BTN_GHOST, "self-start")}>
          <FiRefreshCw className="size-3.5" aria-hidden />
          {d("studio_ui.dock_retry")}
        </button>
      </Section>
    );
  } else if (!models) {
    modelSection = (
      <Section title={d("studio_ui.dock_model")}>
        <div className="vs-film h-[4.5rem] rounded-2xl" role="status" aria-label={d("studio_ui.dock_model")} />
      </Section>
    );
  } else if (name) {
    modelSection = (
      <Section title={d("studio_ui.dock_model")}>
        <p className="text-sm font-semibold text-foreground">{name}</p>
      </Section>
    );
  }

  // Сообщения дока — и в самом окне: на телефоне шторка закрывает док, и
  // «подогнали значение» или отказ сервера иначе остались бы под ней. Живая
  // область для диктора — одна, в доке; здесь — просто текст.
  const panelNotes =
    hasNotes || error ? (
      <div className="flex flex-col gap-1 rounded-xl bg-vs-ink/[0.03] px-3 py-2 text-[12px] leading-snug">
        {warning && <p className="text-status-wait">{d(warning)}</p>}
        {notices.map((n, i) => (
          <p key={`${n.key}-${i}`} className="text-status-wait">
            {d(n.key, n.params)}
          </p>
        ))}
        {error && <p className="text-status-fail">{error}</p>}
      </div>
    ) : null;

  // Все четыре характеристики одним списком. Пока выбор сохраняется, список
  // приглушён и не нажимается — с задержкой, чтобы быстрый ответ не мигал.
  const panelBody = (
    <div
      ref={panelRef}
      aria-busy={locked || undefined}
      className={vx(
        "flex flex-col gap-5 transition-opacity duration-200 motion-reduce:transition-none",
        locked && "pointer-events-none opacity-60 delay-150",
      )}
    >
      {panelNotes}
      {modelSection && <div data-dock-part="model">{modelSection}</div>}
      {resolutionPicker && <div data-dock-part="resolution">{resolutionPicker}</div>}
      {durationPicker && (
        <div data-dock-part="duration" className="flex flex-col gap-2.5">
          {durationPicker}
        </div>
      )}
      <div data-dock-part="aspect">{formatPicker}</div>
    </div>
  );
  const doneLabel = t("studio_ui.dock_done", { defaultValue: "Готово" });

  // «Собрать мультфильм» (вошёл, есть снятые сцены), она же выключенная (сцены
  // есть, снятых нет — причина словами рядом) или «Снять мультфильм» гостя, то
  // есть вход. Других действий у дока нет. На телефоне подпись короче: рядом
  // сводка параметров и сумма; полную читает диктор.
  const caption = (full: string, short: string) =>
    wide ? (
      <span className="min-w-0 truncate">{full}</span>
    ) : (
      <>
        <span className="min-w-0 truncate" aria-hidden>
          {short}
        </span>
        <span className="sr-only">{full}</span>
      </>
    );
  const assembleShort = t("studio_ui.dock_cta_short", { defaultValue: "Собрать" });
  let primaryButton: ReactNode = null;
  let primaryReason: string | null = null;
  if (primary?.kind === "guest") {
    primaryButton = (
      <button type="button" onClick={primary.onClick} className={vx(CS_RUN_GOLD, "min-w-0 max-w-full max-md:!px-4")}>
        <FiFilm className="size-4 shrink-0" aria-hidden />
        {caption(t("studio_ui.guest_cta_btn"), t("studio_ui.dock_guest_short", { defaultValue: "Снять" }))}
      </button>
    );
  } else if (primary?.kind === "assemble") {
    const progress = t("studio_ui.dock_cta_ready", {
      defaultValue: "Снято сцен: {{ready}} из {{total}}",
      ready: primary.ready,
      total: primary.total,
    });
    const assembling = t("studio_ui.dock_cta_assembling", { defaultValue: "Собираем…" });
    primaryButton = (
      <button
        type="button"
        // Не disabled, пока собирается: кнопка остаётся в фокусе, подпись — в полную яркость.
        onClick={() => {
          if (!primary.busy) primary.onClick();
        }}
        aria-disabled={primary.busy || undefined}
        aria-busy={primary.busy || undefined}
        title={progress}
        className={vx(
          CS_RUN_GOLD,
          "min-w-0 max-w-full max-md:!px-4",
          // Кольцо «готово» — когда сняты все сцены, а склейки ещё не было: время собирать.
          primary.ready === primary.total && primary.fresh && !primary.busy && "vs-ready",
          primary.busy && "!cursor-wait active:!scale-100",
        )}
      >
        {primary.busy ? (
          <FiLoader className="size-4 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden />
        ) : (
          <FiFilm className="size-4 shrink-0" aria-hidden />
        )}
        {primary.busy ? caption(assembling, assembling) : caption(t("studio_ui.assemble"), assembleShort)}
        <span className="sr-only">. {progress}</span>
      </button>
    );
  } else if (primary?.kind === "assemble_off") {
    primaryReason = t("studio_ui.dock_cta_off_reason", { defaultValue: "Сначала снимите хотя бы одну сцену" });
    primaryButton = (
      // Не disabled, а aria-disabled: кнопка остаётся в фокусе, и диктор читает причину.
      // На телефоне причина спрятана (места нет) — нажатие показывает её строкой под доком.
      <button
        type="button"
        onClick={() => setHint(true)}
        aria-disabled
        aria-describedby={reasonId}
        title={primaryReason}
        className={vx(CS_RUN_OFF, "min-w-0 max-w-full !cursor-not-allowed max-md:!px-4")}
      >
        <FiFilm className="size-4 shrink-0" aria-hidden />
        {caption(t("studio_ui.assemble"), assembleShort)}
      </button>
    );
  }

  // Подпись — «К съёмке: N», а не «Итого»: рядом с «Собрать мультфильм» сумма
  // читалась как цена склейки, а склейка бесплатна. Это цена ещё не снятых сцен.
  const totalTitle = d("studio_ui.dock_total_title", { count: total.count });
  const toTimeline = t("studio_ui.dock_cta_total", { defaultValue: "К ленте сцен" });
  const unavailable = t("studio_ui.price_unavailable", { defaultValue: "Цена сейчас недоступна" });
  const totalBody = (
    <>
      <span className={vx(TOTAL_LABEL, "max-w-full truncate")} aria-hidden>
        {t("studio_ui.dock_total_short", { defaultValue: "К съёмке: {{count}}", count: total.count })}
      </span>
      <span className="max-w-[9rem] text-sm font-semibold tabular-nums text-foreground" aria-hidden>
        {total.credits != null ? credits(total.credits) : wide ? unavailable : "—"}
      </span>
      <span className="sr-only">
        {totalTitle}, {total.credits != null ? credits(total.credits) : unavailable}
      </span>
    </>
  );
  const totalNode =
    total.count > 0 ? (
      onTotal ? (
        // Сумма ведёт к ленте: там видно, из каких сцен она сложилась.
        <button
          type="button"
          onClick={onTotal}
          title={`${totalTitle} · ${toTimeline}`}
          className={vx(TOTAL, "cursor-pointer transition-colors hover:bg-vs-ink/[0.06]", VS_FOCUS)}
        >
          {totalBody}
          <span className="sr-only">. {toTimeline}</span>
        </button>
      ) : (
        <div className={TOTAL} title={totalTitle}>
          {totalBody}
        </div>
      )
    ) : null;

  return (
    <>
      {/* Панель — как у видеостудии: непрозрачная (vs-solid), на телефоне плотнее и с
          меньшим скруглением. data-vs-composer — та же короткая тень в светлой теме:
          оболочка режет тень по своим полям (globals.css). */}
      <div role="region" aria-label={d("studio_ui.dock_label")} data-vs-composer="" className="vs-root text-foreground">
        <div className="vs-solid flex flex-col gap-1.5 rounded-[20px] p-2 transition-[border-color] duration-200 focus-within:!border-vs-ink/25 md:gap-2 md:rounded-[24px] md:p-3">
          {/* Сообщения: область живая всегда, иначе диктор пропустил бы первое. */}
          <div
            role="status"
            aria-live="polite"
            className={hasNotes ? "flex items-start gap-2 rounded-xl bg-vs-ink/[0.03] py-1.5 pl-3 pr-1.5" : "sr-only"}
          >
            {hasNotes && (
              <>
                <div className="min-w-0 flex-1 space-y-0.5 py-1 text-[12px] leading-snug text-status-wait">
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
            <div className="flex items-start gap-2 rounded-xl bg-status-fail/[0.06] py-1.5 pl-3 pr-1.5">
              <p role="alert" className="min-w-0 flex-1 py-1 text-[12px] leading-snug text-status-fail">
                {error}
              </p>
              {onDismissError && (
                <button type="button" onClick={onDismissError} aria-label={d("studio_ui.dock_hide_notice")} className={closeBtn}>
                  <FiX className="size-4" aria-hidden />
                </button>
              )}
            </div>
          )}

          {/* С 768 px — всё в одну строку: кнопки значений (листаются вбок), сумма и
              главная кнопка справа, как «Создать» у видеостудии. Телефон — тоже одна
              строка: сводка параметров, сумма, короткая главная кнопка. */}
          {wide ? (
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
              <div
                ref={pillsRef}
                // Поля внутри прокрутки — чтобы кольцо фокуса у кнопок не срезалось.
                className={vx("vs-noscroll -my-1 min-w-0 flex-1 basis-0 overflow-x-auto px-0.5 py-1", EDGE_FADE[pillsFade])}
                aria-busy={locked || undefined}
              >
                <div ref={pillsRowRef} className="flex w-max items-center gap-1.5">
                  {modelPill}
                  {valuePill("resolution", d("studio_ui.dock_quality"), resText)}
                  {valuePill("duration", d("studio_ui.dock_duration"), durText)}
                  {aspectPill}
                </div>
              </div>
              {totalNode}
              {primaryButton && <div className="ml-auto flex min-w-0 max-w-full shrink-0">{primaryButton}</div>}
            </div>
          ) : (
            <div className="flex items-center gap-1.5">
              {chip}
              {totalNode}
              {primaryButton && <div className="flex min-w-0 shrink-0">{primaryButton}</div>}
            </div>
          )}
          {/* Крутилка — на самой кнопке (spinning), здесь только текст для чтеца. */}
          {saving && <span className="sr-only">{d("studio_ui.dock_saving")}</span>}
          {/* Причина выключенной «Собрать мультфильм» есть всегда (её читает диктор); на
              телефоне видна только после нажатия на кнопку. */}
          {primaryReason && (
            <p
              id={reasonId}
              className={wide || hint ? "px-1 text-right text-xs leading-snug text-muted" : "sr-only"}
            >
              {primaryReason}
            </p>
          )}
        </div>
      </div>

      {wide ? (
        // Одно окошко над кнопками значений; выбор его не закрывает — только «Готово»,
        // Esc, повторное нажатие на кнопку или клик мимо.
        <AnchoredPopover
          anchor={pillsRowRef}
          open={isOpen}
          onClose={closePanel}
          role="dialog"
          ariaLabel={d("studio_ui.dock_label")}
          closeOnTabOut
          className="vs-root"
        >
          <div className="flex min-h-0 w-[min(24rem,calc(100vw-1rem))] flex-col">
            <div className="flex shrink-0 items-center gap-2 px-4 pb-1 pt-3.5">
              <h2 className={vx(VS_LABEL, "min-w-0 flex-1 truncate")}>{d("studio_ui.dock_label")}</h2>
              {saving && spinner()}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-3 pt-2">{panelBody}</div>
            <div className="flex shrink-0 justify-end border-t border-vs-ink/10 px-4 py-2.5">
              <button type="button" onClick={closePanel} className={VS_BTN_GHOST}>
                {doneLabel}
              </button>
            </div>
          </div>
        </AnchoredPopover>
      ) : (
        // Телефон: все четыре пикера одной шторкой, как «Параметры» видеостудии.
        // Выбор её не закрывает — «Готово» внизу, крестик, свайп или тап по фону.
        <BottomSheet
          open={isOpen}
          onClose={closePanel}
          title={d("studio_ui.dock_label")}
          className="vs-root"
          zIndex={1050}
          footer={
            <button type="button" onClick={closePanel} className={vx(VS_BTN_GHOST, "w-full")}>
              {doneLabel}
            </button>
          }
        >
          <div className="pt-1">{panelBody}</div>
        </BottomSheet>
      )}
    </>
  );
}
