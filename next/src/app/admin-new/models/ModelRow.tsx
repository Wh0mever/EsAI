"use client";

import { FiCheck } from "react-icons/fi";
import { Badge, CARD, Switch, btn } from "../vstudio-showcase/parts";
import {
  CARTOON_STAGES,
  CATEGORIES,
  KIND_LABEL,
  flagViews,
  kindOf,
  ru,
  tariffIgnored,
  tariffUnit,
  type Model,
  type RowForm,
} from "./modelsAdmin";

const FIELD =
  "rounded-lg bg-surface-2 border border-border px-3 text-sm text-foreground focus:border-accent outline-none disabled:opacity-60";
const ROW_INPUT = `${FIELD} py-2`;
const ROW_SELECT = `${FIELD} py-1.5`;

/**
 * Сетка ценовых столбцов: на широком экране строки выстраиваются под общей
 * шапкой (ModelsHead), на узком каждое поле подписано само.
 */
export const PRICE_GRID =
  "grid grid-cols-2 gap-3 lg:grid-cols-[minmax(0,1.3fr)_7.5rem_7.5rem_minmax(0,1fr)_minmax(0,1.15fr)] lg:items-start";

/** Подпись поля: на широком экране её заменяет шапка, но для чтения с экрана она остаётся. */
const CAPTION = "mb-1 block text-xs text-muted lg:sr-only";

export function ModelsHead({ modeLabel }: { modeLabel: string }) {
  return (
    <div
      aria-hidden
      className={`${PRICE_GRID} hidden px-4 text-[11px] font-medium uppercase tracking-wide text-muted-2 lg:grid`}
    >
      <span>Модель</span>
      <span>Тариф</span>
      <span>Наценка, %</span>
      <span>Себестоимость</span>
      <span>Цена · {modeLabel}</span>
    </div>
  );
}

type Props = {
  model: Model;
  form: RowForm;
  /** Строку правили: есть что сохранить или отменить. */
  dirty: boolean;
  /** Правка меняет цену — колонка «Цена» до сохранения устарела. */
  priceStale: boolean;
  busy: boolean;
  flash: boolean;
  error: string | null;
  highlight: boolean;
  onChange: (patch: Partial<RowForm>) => void;
  onSave: () => void;
  onReset: () => void;
};

/**
 * Модель в списке: тариф, своя наценка, себестоимость (у картинок — вводится
 * здесь, у видео и текста — из каталога OpenRouter), цена типичной генерации
 * в действующем режиме и в другом, и доступность — категория, мультстудия,
 * видеостудия, «рекомендуем», «бесплатная», «активна».
 */
export default function ModelRow({
  model: m,
  form,
  dirty,
  priceStale,
  busy,
  flash,
  error,
  highlight,
  onChange,
  onSave,
  onReset,
}: Props) {
  const kind = kindOf(form.category);
  const ignored = tariffIgnored(m, form);
  const pricing = m.pricing;
  const flags = flagViews(pricing?.flags ?? []);
  const effective = pricing?.effectiveMarkupPct;
  const vstudioToggle = kind === "video" || kind === "image";
  // Включённый тумблер у незнакомой студии модели можно только выключить.
  const vstudioLocked = !m.vstudioSupported && !form.vstudioEnabled;
  // Подсказка — по сохранённому: что действует сейчас, пока правку не сохранили.
  const markupHint =
    form.markupPct.trim() === ""
      ? m.markupPct === null && effective
        ? `общая: ${ru(effective)} %`
        : "общая"
      : m.markupPct !== null && effective && Number(effective) !== m.markupPct
        ? `действует порог ${ru(effective)} %`
        : kind === "text"
          ? "для пересчёта тарифа"
          : "своя у модели";

  return (
    <li
      id={`model-${m.id}`}
      className={`${CARD} scroll-mt-32 p-3 sm:p-4 ${highlight ? "border-accent" : ""} ${
        form.isActive ? "" : "opacity-70"
      }`}
    >
      <div className={PRICE_GRID}>
        {/* Модель */}
        <div className="col-span-2 min-w-0 lg:col-span-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="break-words font-medium">{m.name}</span>
            <Badge tone="muted">{KIND_LABEL[kind]}</Badge>
            {!m.isActive && (
              <Badge tone="wait" title="Покупатели модель не видят">
                выключена
              </Badge>
            )}
          </div>
          <div className="mt-0.5 break-all font-mono text-xs text-muted-2">{m.openrouterId}</div>
        </div>

        {/* Тариф */}
        <label className="min-w-0 text-sm">
          <span className={CAPTION}>Тариф</span>
          <input
            type="text"
            inputMode="decimal"
            value={form.coefficient}
            onChange={(e) => onChange({ coefficient: e.target.value })}
            disabled={busy}
            className={`${ROW_INPUT} w-full tabular-nums`}
          />
          <span className="mt-1 block text-[11px] text-muted-2">
            {tariffUnit(m, form)}
            {ignored && <span className="text-status-wait"> · сейчас не действует</span>}
          </span>
        </label>

        {/* Своя наценка */}
        <label className="min-w-0 text-sm">
          <span className={CAPTION}>Наценка, %</span>
          <input
            type="text"
            inputMode="decimal"
            value={form.markupPct}
            placeholder="общая"
            onChange={(e) => onChange({ markupPct: e.target.value })}
            disabled={busy}
            className={`${ROW_INPUT} w-full tabular-nums`}
          />
          <span className="mt-1 block text-[11px] text-muted-2">{markupHint}</span>
        </label>

        {/* Себестоимость */}
        <div className="col-span-2 min-w-0 text-sm lg:col-span-1">
          <span className={CAPTION}>Себестоимость</span>
          {kind === "image" ? (
            <div className="grid grid-cols-2 gap-2">
              <label className="min-w-0">
                <input
                  type="text"
                  inputMode="decimal"
                  value={form.unitCost}
                  placeholder="не задана"
                  onChange={(e) => onChange({ unitCost: e.target.value })}
                  disabled={busy}
                  className={`${ROW_INPUT} w-full tabular-nums`}
                />
                <span className="mt-1 block text-[11px] text-muted-2">$ за картинку</span>
              </label>
              <label className="min-w-0">
                <input
                  type="text"
                  inputMode="decimal"
                  value={form.refCost}
                  placeholder="0"
                  onChange={(e) => onChange({ refCost: e.target.value })}
                  disabled={busy}
                  className={`${ROW_INPUT} w-full tabular-nums`}
                />
                <span className="mt-1 block text-[11px] text-muted-2">$ за входное фото</span>
              </label>
            </div>
          ) : (
            <div className={`break-words lg:pt-2 ${m.costSample ? "text-foreground" : "text-muted-2"}`}>
              {m.costSample ?? (kind === "text" ? "нет цены в каталоге" : "—")}
            </div>
          )}
        </div>

        {/* Цена */}
        <div className="col-span-2 min-w-0 text-sm lg:col-span-1 lg:pt-2">
          <span className={CAPTION}>Цена</span>
          <div className={`break-words font-semibold tabular-nums ${priceStale ? "text-muted" : "text-foreground"}`}>
            {m.priceSample ?? "—"}
          </div>
          {m.priceSampleOther && (
            <div className="break-words text-[11px] text-muted-2">{m.priceSampleOther}</div>
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
          {priceStale && <div className="mt-1 text-[11px] text-status-wait">пересчитается после сохранения</div>}
        </div>
      </div>

      {/* Доступность */}
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border pt-3">
        <label className="flex items-center gap-2 text-xs text-muted">
          Категория
          <select
            value={form.category}
            onChange={(e) => onChange({ category: e.target.value })}
            disabled={busy}
            className={`${ROW_SELECT} w-40`}
          >
            {CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
            {!CATEGORIES.some((c) => c.value === form.category) && (
              <option value={form.category}>{form.category}</option>
            )}
          </select>
        </label>
        <label className="flex items-center gap-2 text-xs text-muted">
          Мультстудия
          <select
            value={form.cartoonStage}
            onChange={(e) => onChange({ cartoonStage: e.target.value })}
            disabled={busy}
            className={`${ROW_SELECT} w-36`}
          >
            {CARTOON_STAGES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        {vstudioToggle && (
          <Switch
            on={form.vstudioEnabled}
            label="Видеостудия"
            title={
              vstudioLocked
                ? "Видеостудия пока не знает эту модель — показать её можно только в чате"
                : "Показывать модель в видеостудии"
            }
            disabled={busy || vstudioLocked}
            onChange={(on) => onChange({ vstudioEnabled: on })}
          />
        )}
        <label className="inline-flex min-h-9 cursor-pointer items-center gap-2 text-xs text-muted">
          <input
            type="checkbox"
            className="h-4 w-4 accent-accent"
            checked={form.recommended}
            onChange={(e) => onChange({ recommended: e.target.checked })}
            disabled={busy}
          />
          ⭐ Рекомендуем
        </label>
        <label className="inline-flex min-h-9 cursor-pointer items-center gap-2 text-xs text-muted">
          <input
            type="checkbox"
            className="h-4 w-4 accent-accent"
            checked={form.freeTier}
            onChange={(e) => onChange({ freeTier: e.target.checked })}
            disabled={busy}
          />
          Бесплатная
        </label>
        <label className="inline-flex min-h-9 cursor-pointer items-center gap-2 text-xs text-muted">
          <input
            type="checkbox"
            className="h-4 w-4 accent-accent"
            checked={form.isActive}
            onChange={(e) => onChange({ isActive: e.target.checked })}
            disabled={busy}
          />
          Активна
        </label>

        <div className="ml-auto flex items-center gap-2">
          {flash && (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-400">
              <FiCheck className="h-4 w-4" aria-hidden /> Сохранено
            </span>
          )}
          {dirty && (
            <>
              <button type="button" onClick={onReset} disabled={busy} className={btn("plain")}>
                Отменить
              </button>
              <button type="button" onClick={onSave} disabled={busy} className={btn("primary")}>
                {busy ? "Сохранение…" : "Сохранить"}
              </button>
            </>
          )}
        </div>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-xs text-status-fail">
          {error}
        </p>
      )}
    </li>
  );
}
