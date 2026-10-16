"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { FiAlertTriangle, FiCheck, FiFilm, FiLock, FiPercent, FiRefreshCw } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import { Badge, Skeleton, btn, chip } from "../vstudio-showcase/parts";
import Dialog from "../studio-scenes/Dialog";
import {
  MODE_LABEL,
  PRICING_PATH,
  PRICING_PREVIEW_PATH,
  SETTINGS_PATH,
  SCENE_CREDITS_MAX,
  changeLines,
  creditsText,
  deltaText,
  draftChanges,
  draftFrom,
  errorText,
  flagViews,
  hasErrors,
  modeSwitchExamples,
  parsePricing,
  pinDraft,
  previousMarkup,
  ru,
  serverErrors,
  typedSceneCredits,
  type Draft,
  type FieldErrors,
  type Pricing,
  type PricingMode,
  type Sample,
} from "./pricingSettings";

const INPUT =
  "rounded-lg bg-surface-2 border border-border px-3 py-2 text-sm text-foreground focus:border-accent outline-none disabled:opacity-60";

const SAVE_BTN =
  "rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50";
const PLAIN_BTN =
  "rounded-lg border border-border bg-surface-2 px-3 py-2 text-xs font-semibold text-foreground transition-opacity hover:opacity-90 disabled:opacity-50";

/** Пауза после последней правки, прежде чем пересчитать примеры. */
const PREVIEW_DELAY_MS = 300;

const MODES: { value: PricingMode; hint: string }[] = [
  {
    value: "legacy",
    hint:
      "Цена — тариф модели, но не ниже себестоимости ÷ 0,6 по самому дешёвому кредиту, как работало до сих пор. " +
      "Наценка, порог и курс ниже в этом режиме не действуют: примеры показывают, какими станут цены после переключения.",
  },
  {
    value: "markup",
    hint:
      "Цена = себестоимость OpenRouter + наценка, делённая на цену кредита, с округлением вверх. Тарифы видео и " +
      "картинок с себестоимостью не действуют — кроме картинок Nano Banana в чате: там по-прежнему токены × тариф, " +
      "его подгоняет под наценку кнопка «Тариф картинок в чате». Текст списывается по тарифам — их пересчёт " +
      "кнопкой в «Моделях».",
  },
];

function SavedFlash() {
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-400">
      <FiCheck className="h-4 w-4" /> Сохранено
    </span>
  );
}

function FieldError({ text }: { text?: string }) {
  if (!text) return null;
  return <span className="text-xs text-status-fail">{text}</span>;
}

type PreviewState = { key: string; data: Pricing };
type PreviewFail = { key: string; text: string; errors: FieldErrors };

/**
 * «Цены и наценка» (просьба клиента 15.10.2026: процент наценки к себестоимости
 * OpenRouter — общий и у каждой модели). Режим legacy/markup, наценка, нижний
 * порог, курс сома и живая таблица примеров «по-старому → с наценкой», которая
 * пересчитывается на сервере с несохранёнными значениями. Здесь же «цена сцены
 * 5 с» мультфильма: она действует только в режиме legacy. Карточка грузится
 * сама — страница настроек её не ждёт.
 */
export default function PricingSection() {
  const [tick, setTick] = useState(0);
  const [loaded, setLoaded] = useState<{ tick: number; error: string | null } | null>(null);
  const [saved, setSaved] = useState<Pricing | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  // Карточку перечитали без правки настроек (сохранили цену сцены) — примеры пересчитать.
  const [version, setVersion] = useState(0);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [previewFail, setPreviewFail] = useState<PreviewFail | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveFail, setSaveFail] = useState<PreviewFail | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [flash, setFlash] = useState(false);

  const [sceneDraft, setSceneDraft] = useState("");
  const [sceneSaving, setSceneSaving] = useState(false);
  const [sceneError, setSceneError] = useState<string | null>(null);
  const [sceneFlash, setSceneFlash] = useState(false);

  const loading = loaded?.tick !== tick;

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<unknown>(PRICING_PATH, "GET", undefined, true);
      if (!alive) return;
      const data = res.ok ? parsePricing(res.data) : null;
      if (data) {
        setSaved(data);
        setDraft(draftFrom(data));
        setSceneDraft(data.sceneCredits === null ? "" : String(data.sceneCredits));
      }
      setLoaded({ tick, error: data ? null : errorText(res, "Не удалось загрузить настройки цен") });
      // Ссылка «Настройки → Цены и наценка» из «Моделей»: страница грузится не
      // сразу, и браузер не находит якорь сам.
      if (data && window.location.hash === "#pricing") {
        requestAnimationFrame(() => document.getElementById("pricing")?.scrollIntoView({ block: "start" }));
      }
    })();
    return () => {
      alive = false;
    };
  }, [tick]);

  const changes = useMemo(() => (saved && draft ? draftChanges(draft, saved) : null), [draft, saved]);
  const bodyJson = JSON.stringify(changes?.body ?? {});
  const dirty = bodyJson !== "{}";
  const valid = changes !== null && !hasErrors(changes.errors);
  // Набрали неверное число — тела нет, но форма уже не равна сохранённой.
  const touched = dirty || !valid;
  const key = `${version}|${bodyJson}`;

  // Живое превью: та же проверка, что у сохранения, но сервер ничего не пишет.
  useEffect(() => {
    if (!dirty || !valid) return;
    let alive = true;
    const timer = setTimeout(async () => {
      const res = await fetchData<unknown>(PRICING_PREVIEW_PATH, "POST", bodyJson, true);
      if (!alive) return;
      const data = res.ok ? parsePricing(res.data) : null;
      if (data) setPreview({ key, data });
      else
        setPreviewFail({ key, text: errorText(res, "Примеры не посчитались"), errors: serverErrors(res.data) });
    }, PREVIEW_DELAY_MS);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [key, bodyJson, dirty, valid]);

  const closeConfirm = useCallback(() => setConfirming(false), []);

  if (loading && !saved) {
    return (
      <section id="pricing" className="scroll-mt-32 rounded-2xl border border-border bg-surface p-5" aria-busy="true">
        <Header />
        <div className="mt-4 space-y-3">
          <Skeleton className="h-10" />
          <Skeleton className="h-20" />
          <Skeleton className="h-56" />
        </div>
      </section>
    );
  }

  if (!saved || !draft || !changes) {
    return (
      <section id="pricing" className="scroll-mt-32 rounded-2xl border border-border bg-surface p-5">
        <Header />
        <p className="mt-3 text-sm text-status-fail">{loaded?.error || "Не удалось загрузить настройки цен"}</p>
        <button type="button" onClick={() => setTick((t) => t + 1)} disabled={loading} className={`${PLAIN_BTN} mt-3`}>
          <FiRefreshCw className="mr-1.5 inline h-3.5 w-3.5" aria-hidden />
          {loading ? "Загрузка…" : "Повторить"}
        </button>
      </section>
    );
  }

  const fresh = dirty && valid && preview?.key === key ? preview.data : null;
  const failed = dirty && valid && previewFail?.key === key ? previewFail : null;
  const previewing = dirty && valid && !fresh && !failed;
  // Пока считается новое превью, показываем прошлое (приглушённым), а не прыгаем к сохранённому.
  const shown = fresh ?? (touched && preview ? preview.data : saved);
  const stale = touched && !fresh;
  const savedErrors = saveFail?.key === key ? saveFail.errors : {};
  const errors: FieldErrors = { ...(failed?.errors ?? {}), ...savedErrors, ...changes.errors };
  const set = (patch: Partial<Draft>) => setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
  const busy = saving || sceneSaving;
  const live = saved.liveKgsPerUsd;
  const switching = "mode" in changes.body;

  const reset = () => {
    setDraft(draftFrom(saved));
    setSaveFail(null);
  };

  const save = async (confirmed: boolean) => {
    if (busy || !touched) return;
    if (!valid) {
      setSaveFail({ key, text: "Исправьте поля, отмеченные красным.", errors: {} });
      return;
    }
    if (switching && !confirmed) {
      setConfirming(true);
      return;
    }
    setSaving(true);
    setSaveFail(null);
    const res = await fetchData<unknown>(PRICING_PATH, "PATCH", bodyJson, true);
    setSaving(false);
    const data = res.ok ? parsePricing(res.data) : null;
    if (!data) {
      setSaveFail({ key, text: errorText(res, "Не удалось сохранить цены"), errors: serverErrors(res.data) });
      return;
    }
    setSaved(data);
    setDraft(draftFrom(data));
    setPreview(null);
    setConfirming(false);
    setFlash(true);
    setTimeout(() => setFlash(false), 2000);
  };

  const sceneSaved = saved.sceneCredits === null ? "" : String(saved.sceneCredits);
  const sceneDirty = sceneDraft.trim() !== sceneSaved;

  const saveScene = async () => {
    if (busy) return;
    const credits = typedSceneCredits(sceneDraft);
    if (credits === null) {
      setSceneError(`Цена сцены: целое число от 0 до ${SCENE_CREDITS_MAX}`);
      return;
    }
    setSceneSaving(true);
    setSceneError(null);
    const res = await fetchData<unknown>(SETTINGS_PATH, "PATCH", { studio_scene_credits: credits }, true);
    if (!res.ok) {
      setSceneSaving(false);
      setSceneError(errorText(res, "Не удалось сохранить цену сцены"));
      return;
    }
    // Цена сцены есть в примере «Сцена мультфильма» — перечитываем карточку.
    const again = await fetchData<unknown>(PRICING_PATH, "GET", undefined, true);
    setSceneSaving(false);
    const data = again.ok ? parsePricing(again.data) : null;
    if (data) {
      setSaved(data);
      setVersion((v) => v + 1);
      setSceneDraft(data.sceneCredits === null ? String(credits) : String(data.sceneCredits));
    } else {
      setSaved({ ...saved, sceneCredits: credits });
      setSceneDraft(String(credits));
    }
    setSceneFlash(true);
    setTimeout(() => setSceneFlash(false), 2000);
  };

  const rateSource =
    shown.basis?.rateSource === "pinned"
      ? `курс закреплён: ${ru(shown.basis.kgsPerUsd ?? "")} сом/$`
      : shown.basis?.rateSource === "live"
        ? `курс живой: ${ru(shown.basis.kgsPerUsd ?? "")} сом/$`
        : "";
  const floorWins = Number(shown.floorPct) > Number(shown.markupPct);

  return (
    <section id="pricing" className="scroll-mt-32 rounded-2xl border border-border bg-surface p-5">
      <Header>
        {flash && <SavedFlash />}
        {touched && (
          <button type="button" onClick={reset} disabled={busy} className={PLAIN_BTN}>
            Отменить
          </button>
        )}
        {touched && (
          <button type="button" onClick={() => void save(false)} disabled={busy} className={SAVE_BTN}>
            {saving ? "Сохранение…" : "Сохранить"}
          </button>
        )}
      </Header>
      <p className="mt-1 text-xs text-muted-2">
        Как считается цена генерации на сайте, в боте и в студиях. Сейчас:{" "}
        <span className="text-foreground">{MODE_LABEL[saved.mode]}</span>. Всё применяется сразу после сохранения,
        режим можно вернуть в любой момент. Пока не сохранили — таблица ниже показывает, какими станут цены.
      </p>

      {/* Режим */}
      <div role="radiogroup" aria-label="Режим цен" className="mt-4 flex flex-wrap gap-2">
        {MODES.map((m) => (
          <button
            key={m.value}
            type="button"
            role="radio"
            aria-checked={draft.mode === m.value}
            onClick={() => set({ mode: m.value })}
            disabled={busy}
            className={`${chip(draft.mode === m.value)} min-h-9 disabled:cursor-not-allowed disabled:opacity-50`}
          >
            {MODE_LABEL[m.value]}
          </button>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-muted-2">{MODES.find((m) => m.value === draft.mode)?.hint}</p>

      {/* Наценка, порог, курс */}
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="pricing-markup" className="text-xs text-muted">
            Наценка, %
          </label>
          <input
            id="pricing-markup"
            type="text"
            inputMode="decimal"
            value={draft.markup}
            onChange={(e) => set({ markup: e.target.value })}
            disabled={busy}
            aria-invalid={Boolean(errors.markup_pct)}
            className={INPUT}
          />
          <span className="text-[11px] text-muted-2">
            Общая для всех моделей. Свою наценку модели задают в «Моделях».
          </span>
          <FieldError text={errors.markup_pct} />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="pricing-floor" className="text-xs text-muted">
            Нижний порог, %
          </label>
          <input
            id="pricing-floor"
            type="text"
            inputMode="decimal"
            value={draft.floor}
            onChange={(e) => set({ floor: e.target.value })}
            disabled={busy}
            aria-invalid={Boolean(errors.floor_pct)}
            className={INPUT}
          />
          <span className="text-[11px] text-muted-2">
            Ниже порога наценка не опускается — ни общая, ни своя у модели.
          </span>
          <FieldError text={errors.floor_pct} />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="pricing-rate" className="text-xs text-muted">
            Курс для цен, сом за $
          </label>
          <input
            id="pricing-rate"
            type="text"
            inputMode="decimal"
            value={draft.rate}
            onChange={(e) => set({ rate: e.target.value, pin: false })}
            placeholder={live ? `живой: ${ru(live)}` : "живой курс"}
            disabled={busy}
            aria-invalid={Boolean(errors.kgs_per_usd || errors.pin_live_rate)}
            className={INPUT}
          />
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-2">
            <span>Живой курс: {live ? <span className="text-foreground">{ru(live)} сом/$</span> : "недоступен"}</span>
            <button
              type="button"
              onClick={() => setDraft(pinDraft(draft, saved))}
              disabled={busy || !live}
              className="inline-flex min-h-8 items-center gap-1 text-accent underline-offset-2 hover:underline disabled:cursor-not-allowed disabled:opacity-50"
            >
              <FiLock className="h-3 w-3" aria-hidden />
              Закрепить текущий
            </button>
            {draft.rate.trim() !== "" && (
              <button
                type="button"
                onClick={() => set({ rate: "", pin: false })}
                disabled={busy}
                className="min-h-8 text-muted underline-offset-2 hover:text-foreground hover:underline disabled:opacity-50"
              >
                Брать живой
              </button>
            )}
          </div>
          <span className="text-[11px] text-muted-2">
            Пусто — цены идут за живым курсом. Закреплённый держит цены на месте; ослабнет живой больше чем на 2 % —
            появится предупреждение.
          </span>
          <FieldError text={errors.kgs_per_usd || errors.pin_live_rate} />
        </div>
      </div>

      {/* Основа цены */}
      <div className="mt-4 rounded-xl border border-border bg-surface-2 px-3 py-2.5 text-sm">
        <div className="break-words">
          1 кредит: <span className="font-medium text-foreground">{shown.basisLine || "—"}</span>
        </div>
        <p className="mt-1 text-[11px] text-muted-2">
          Самый дешёвый кредит среди активных пакетов{rateSource ? ` · ${rateSource}` : ""}. Правка{" "}
          <Link href="/admin-new/packages" className="text-accent underline-offset-2 hover:underline">
            пакетов
          </Link>{" "}
          двигает все цены по наценке.
        </p>
        <p className="mt-1 text-xs text-muted">
          Действует наценка: <span className="text-foreground">{ru(shown.effectiveMarkupPct)} %</span>
          {floorWins && ` — порог ${ru(shown.floorPct)} % выше общей наценки ${ru(shown.markupPct)} %`}
        </p>
      </div>

      {/* Предупреждения */}
      {shown.warnings.length > 0 && (
        <ul className="mt-3 flex flex-col gap-2">
          {shown.warnings.map((w) => (
            <li
              key={w.code || w.text}
              className="flex items-start gap-2 rounded-xl border border-status-wait/40 bg-status-wait/10 px-3 py-2 text-xs text-status-wait"
            >
              <FiAlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              <span className="min-w-0 break-words">
                {w.text}
                {w.code === "no_cost" && (
                  <>
                    {" "}
                    <Link href="/admin-new/models" className="font-semibold underline underline-offset-2">
                      Открыть «Модели»
                    </Link>
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      {saveFail?.key === key && saveFail.text && (
        <p role="alert" className="mt-3 text-sm text-status-fail">
          {saveFail.text}
        </p>
      )}

      {/* Примеры */}
      <div className="mt-5 border-t border-border pt-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Примеры цен</h3>
          <span aria-live="polite" className="text-[11px] text-muted-2">
            {!valid
              ? "Исправьте поля — тогда пересчитаю"
              : previewing
                ? "Пересчитываю…"
                : failed
                  ? ""
                  : fresh
                    ? "С несохранёнными значениями"
                    : "По сохранённым настройкам"}
          </span>
        </div>
        {failed && (
          <p className="mt-2 text-xs text-status-fail">
            {failed.text}{" "}
            <button
              type="button"
              onClick={() => setVersion((v) => v + 1)}
              className="font-semibold underline underline-offset-2"
            >
              Повторить
            </button>
          </p>
        )}
        <SamplesTable samples={shown.samples} saved={saved} mode={draft.mode} stale={stale} compare={fresh !== null} />
        <p className="mt-2 text-[11px] text-muted-2">
          «По-старому» и «С наценкой» посчитаны с одними и теми же настройками; действует столбец выбранного режима.
          Сцена мультфильма — кадр и видео 16:9. Текст в обоих режимах идёт по тарифу модели.
        </p>
      </div>

      {/* Мультфильм: цена сцены (только legacy) */}
      <div className="mt-5 border-t border-border pt-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <FiFilm className="h-4 w-4 text-accent" aria-hidden />
            <h3 className="text-sm font-semibold">Мультфильм: цена сцены 5 с</h3>
            <Badge tone="muted" title="В режиме «наценка» сцена = кадр + видео по себестоимости">
              только по-старому
            </Badge>
          </div>
          <div className="flex items-center gap-3">
            {sceneFlash && <SavedFlash />}
            {sceneDirty && (
              <button type="button" onClick={() => void saveScene()} disabled={busy} className={SAVE_BTN}>
                {sceneSaving ? "Сохранение…" : "Сохранить"}
              </button>
            )}
          </div>
        </div>
        <div className="mt-3 flex max-w-xs flex-col gap-1">
          <label htmlFor="pricing-scene" className="text-xs text-muted">
            Кредитов за сцену целиком (0 — по тарифу модели)
          </label>
          <input
            id="pricing-scene"
            type="text"
            inputMode="numeric"
            value={sceneDraft}
            onChange={(e) => setSceneDraft(e.target.value)}
            disabled={busy}
            className={INPUT}
          />
        </div>
        <p className="mt-1 text-[11px] text-muted-2">
          Кадр + видео 5 с, только в режиме «по-старому». Её всё равно поднимает нижняя граница по себестоимости.
          {saved.mode === "markup" && " Сейчас включена наценка — поле не действует, пока режим не вернут."}
        </p>
        {sceneError && <p className="mt-2 text-sm text-status-fail">{sceneError}</p>}
      </div>

      {confirming && (
        <ModeConfirm
          to={draft.mode}
          busy={saving}
          samples={fresh ? fresh.samples : Object.keys(changes.body).length === 1 ? saved.samples : []}
          extra={changeLines(changes.body, saved)}
          effectiveMarkup={(fresh ?? saved).effectiveMarkupPct}
          basisLine={(fresh ?? saved).basisLine}
          withoutCost={(fresh ?? saved).withoutCost}
          chatNotes={(fresh ?? saved).warnings.filter((w) => w.code === "flux_chat_refs").map((w) => w.text)}
          error={saveFail?.key === key ? saveFail.text : null}
          onClose={closeConfirm}
          onConfirm={() => void save(true)}
        />
      )}
    </section>
  );
}

function Header({ children }: { children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <FiPercent className="h-4 w-4 text-accent" aria-hidden />
        <h2 className="text-base font-semibold">Цены и наценка</h2>
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

/**
 * Примеры «по-старому → с наценкой». На телефоне три столбца: себестоимость и
 * разница уходят строкой под название примера.
 */
function SamplesTable({
  samples,
  saved,
  mode,
  stale,
  compare,
}: {
  samples: Sample[];
  saved: Pricing;
  mode: PricingMode;
  stale: boolean;
  /** Показаны несохранённые значения — рядом с ценой «было». */
  compare: boolean;
}) {
  if (samples.length === 0) {
    return <p className="mt-3 text-sm text-muted">Примеров нет: сервер их не прислал.</p>;
  }
  const head = (which: PricingMode, label: string) => (
    <th scope="col" className="px-2 py-2 text-right font-medium">
      <span className={mode === which ? "text-accent" : ""}>{label}</span>
      {mode === which && <span className="block text-[10px] normal-case tracking-normal text-accent">действует</span>}
    </th>
  );
  const cell = (which: PricingMode) =>
    `px-2 py-2 text-right tabular-nums whitespace-nowrap ${
      mode === which ? "font-semibold text-foreground" : "text-muted"
    }`;

  return (
    <div className={`mt-3 overflow-x-auto transition-opacity ${stale ? "opacity-60" : ""}`}>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted-2">
            <th scope="col" className="py-2 pr-2 font-medium">
              Пример
            </th>
            <th scope="col" className="hidden px-2 py-2 text-right font-medium sm:table-cell">
              Себестоимость
            </th>
            {head("legacy", "По-старому")}
            {head("markup", "С наценкой")}
            <th scope="col" className="hidden py-2 pl-2 text-right font-medium sm:table-cell">
              Разница
            </th>
          </tr>
        </thead>
        <tbody>
          {samples.map((s) => {
            const was = compare ? previousMarkup(saved, s.key) : null;
            const delta = deltaText(s.deltaPct);
            const unsold = s.markup === null && (s.kind === "video" || s.kind === "cartoon");
            const flags = flagViews(s.flags);
            return (
              <tr key={s.key} className="border-b border-border align-top last:border-0">
                <td className="py-2 pr-2">
                  <div className="break-words text-foreground">{s.label}</div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-2 sm:hidden">
                    {s.costText && <span>{s.costText}</span>}
                    {delta && <span>{delta}</span>}
                  </div>
                  {s.kind === "text" && s.afterRecompute !== null && (
                    <div className="mt-0.5 text-[11px] text-muted-2">
                      после «Пересчитать тарифы текста»: {s.afterRecompute} кр
                    </div>
                  )}
                  {flags.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {flags.map((f) => (
                        <Badge key={f.label} tone={f.tone} title={f.title}>
                          {f.label}
                        </Badge>
                      ))}
                    </div>
                  )}
                </td>
                <td className="hidden px-2 py-2 text-right tabular-nums text-muted sm:table-cell">
                  {s.costText ?? "—"}
                </td>
                <td className={cell("legacy")}>{creditsText(s.legacy)}</td>
                <td className={cell("markup")}>
                  {unsold ? <span className="text-status-wait">не продаётся</span> : creditsText(s.markup)}
                  {was !== null && was !== s.markup && (
                    <span className="block text-[11px] font-normal text-muted-2 line-through">{was} кр</span>
                  )}
                </td>
                <td className="hidden py-2 pl-2 text-right tabular-nums text-muted sm:table-cell">{delta ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Подтверждение смены режима: что поменяется для покупателя, до сохранения. */
function ModeConfirm({
  to,
  busy,
  samples,
  extra,
  effectiveMarkup,
  basisLine,
  withoutCost,
  chatNotes,
  error,
  onClose,
  onConfirm,
}: {
  to: PricingMode;
  busy: boolean;
  samples: Sample[];
  extra: string[];
  effectiveMarkup: string;
  basisLine: string;
  withoutCost: number;
  /** Где чат пока берёт не так, как студии (FLUX с фото) — сказать до переключения. */
  chatNotes: string[];
  error: string | null;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const examples = modeSwitchExamples(samples, to);
  const markup = to === "markup";
  const points = markup
    ? [
        `Видео в чате, боте, видеостудии и мультфильмах: себестоимость OpenRouter + наценка ${ru(effectiveMarkup)} %, кредит — ${basisLine || "самый дешёвый пакет"}. Тарифы видеомоделей перестают действовать.`,
        withoutCost > 0
          ? `Моделей без себестоимости: ${withoutCost}. Видео без себестоимости не продаётся — человек увидит «Цена модели сейчас недоступна». Картинки без себестоимости остаются по прежней цене.`
          : "Видео без себестоимости не продаётся; картинки без себестоимости остаются по прежней цене.",
        "Сцена мультфильма = кадр + видео в пропорциях проекта; «цена сцены 5 с» и ручные цены сцен не действуют.",
        "Текст списывается по прежним тарифам. Пересчитать их от себестоимости — кнопкой «Пересчитать тарифы текста» в «Моделях».",
        "Картинки Nano Banana в чате списываются по токенам × тариф и после переключения стоят как раньше. Подогнать их под наценку — кнопкой «Тариф картинок в чате» в «Моделях».",
        ...chatNotes,
        "Новые цены видны покупателям сразу. Вернуть — переключить обратно, тоже мгновенно.",
      ]
    : [
        "Цены вернутся к тарифам моделей с нижней границей по себестоимости — как до переключения.",
        "«Цена сцены 5 с» мультфильма снова действует.",
        "Тарифы текста и картинок в чате, пересчитанные кнопками, останутся новыми; прежние значения — в журнале действий. Тариф Nano Banana в режиме «по-старому» — ещё и цена картинки в студиях.",
        "Новые цены видны покупателям сразу.",
      ];

  return (
    <Dialog
      title={markup ? "Включить цены по наценке?" : "Вернуть цены по-старому?"}
      subtitle="Меняется цена всех генераций на сайте, в боте и в студиях."
      busy={busy}
      onClose={onClose}
      onSubmit={onConfirm}
      error={error}
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy} className={btn("plain", "lg")}>
            Отмена
          </button>
          <button type="submit" disabled={busy} className={btn("primary", "lg")}>
            {busy ? "Сохраняю…" : markup ? "Включить наценку" : "Вернуть по-старому"}
          </button>
        </>
      }
    >
      <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted">
        {points.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
      {examples.length > 0 && (
        <div>
          <div className="text-xs text-muted-2">Например:</div>
          <ul className="mt-1 space-y-1 text-sm">
            {examples.map((e) => (
              <li key={e} className="tabular-nums text-foreground">
                {e}
              </li>
            ))}
          </ul>
        </div>
      )}
      {extra.length > 0 && (
        <div>
          <div className="text-xs text-muted-2">Вместе с режимом сохранится:</div>
          <ul className="mt-1 space-y-1 text-sm text-foreground">
            {extra.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      )}
    </Dialog>
  );
}
