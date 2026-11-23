"use client";

import { useMemo, useState, type ReactNode } from "react";
import { FiAlertTriangle, FiGrid, FiLock, FiPercent, FiToggleRight } from "react-icons/fi";
import { Badge, CARD, INPUT, Switch, btn, chip } from "../vstudio-showcase/parts";
import Dialog from "../studio-scenes/Dialog";
import {
  KIND_LABEL,
  MODE_CHOICES,
  MODE_HINT,
  MODE_LABEL,
  SUPERUSER_TEXT,
  categoryLabel,
  changedPreview,
  choiceLabel,
  creditsText,
  estimateCredits,
  markupChange,
  markupSource,
  modeAfter,
  ownChange,
  ownDraft,
  pctText,
  previewRows,
  ru,
  typedNumber,
  usdText,
  type ModeChoice,
  type PreviewRow,
  type Settings,
  type ToolRow,
} from "./creativeAdmin";

export type PatchResult = { ok: true } | { ok: false; error: string };
type Patch = (body: Record<string, unknown>, okText: string) => Promise<PatchResult>;

function CardHeader({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        {icon}
        <h2 className="text-base font-semibold">{title}</h2>
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

const ICON = "h-4 w-4 text-accent";

/* ------------------------------------------------------------------ */
/* Режим                                                               */
/* ------------------------------------------------------------------ */

/**
 * Кому открыт раздел. Выбор сразу спрашивает подтверждение: режим меняет,
 * кто может тратить кредиты, — случайный клик не должен открыть раздел всем.
 */
export function ModeCard({ settings, onPatch }: { settings: Settings; onPatch: Patch }) {
  const current: ModeChoice = settings.modeOverride ?? "";
  const [target, setTarget] = useState<ModeChoice | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const open = (choice: ModeChoice) => {
    if (choice === current) return;
    setError(null);
    setTarget(choice);
  };

  const confirm = async () => {
    if (target === null) return;
    setBusy(true);
    setError(null);
    const res = await onPatch({ mode: target }, `Режим: ${MODE_LABEL[modeAfter(target, settings.modeEnv)].toLowerCase()}`);
    setBusy(false);
    if (res.ok) setTarget(null);
    else setError(res.error);
  };

  const after = target === null ? null : modeAfter(target, settings.modeEnv);

  return (
    <section className={`${CARD} p-5`}>
      <CardHeader icon={<FiToggleRight className={ICON} aria-hidden />} title="Кому открыт раздел" />
      <p className="mt-1 text-xs text-muted-2">
        Сейчас: <span className="font-medium text-foreground">{MODE_LABEL[settings.mode]}</span> · в окружении:{" "}
        {MODE_LABEL[settings.modeEnv].toLowerCase()}
        {settings.modeOverride ? " · задано здесь" : ""}. Пункт меню на сайте появляется только в сборке с
        NEXT_PUBLIC_CREATIVE_NAV=1 — режим решает, кто может запускать инструменты.
      </p>
      <div role="radiogroup" aria-label="Режим раздела" className="mt-4 flex flex-wrap gap-2">
        {MODE_CHOICES.map((choice) => (
          <button
            key={choice || "env"}
            type="button"
            role="radio"
            aria-checked={current === choice}
            title={MODE_HINT[modeAfter(choice, settings.modeEnv)]}
            onClick={() => open(choice)}
            className={`${chip(current === choice)} min-h-9`}
          >
            {choiceLabel(choice, settings.modeEnv)}
          </button>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-muted-2">{MODE_HINT[settings.mode]}</p>

      {target !== null && after !== null && (
        <Dialog
          title={`Режим: ${MODE_LABEL[after].toLowerCase()}?`}
          subtitle={target === "" ? "Правка из админки снимется — действует режим из окружения." : undefined}
          busy={busy}
          onClose={() => setTarget(null)}
          onSubmit={() => void confirm()}
          error={error}
          footer={
            <>
              <button type="button" onClick={() => setTarget(null)} disabled={busy} className={btn("plain", "lg")}>
                Отмена
              </button>
              <button type="submit" disabled={busy} className={btn("primary", "lg")}>
                {busy ? "Сохраняю…" : "Переключить"}
              </button>
            </>
          }
        >
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted">
            <li>
              Было: <span className="text-foreground">{MODE_LABEL[settings.mode]}</span>, станет:{" "}
              <span className="text-foreground">{MODE_LABEL[after]}</span>.
            </li>
            <li>{MODE_HINT[after]}</li>
            {after === "on" && <li>Проверьте цены инструментов ниже: покупатели увидят их сразу.</li>}
            <li>Сервер подхватывает новый режим в течение ~30 секунд. Вернуть можно в любой момент.</li>
          </ul>
        </Dialog>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Общая наценка                                                       */
/* ------------------------------------------------------------------ */

const PREVIEW_LIMIT = 15;

/** «Перенос движения · 5 с, 480p: 123 → ≈150 кр». */
function previewLine(r: PreviewRow): string {
  const label = r.label ? ` · ${r.label}` : "";
  return `${r.name}${label}: ${creditsText(r.now)} → ≈${creditsText(r.next)}`;
}

/**
 * Общая наценка к себестоимости — для всех инструментов без своей. Пока не
 * сохранили, ниже видно, какие цены и как поменяются (считается здесь же по
 * формуле сервера, поэтому «≈»). Сохранение — через подтверждение.
 */
export function MarkupCard({
  settings,
  canEditMoney,
  onPatch,
}: {
  settings: Settings;
  canEditMoney: boolean;
  onPatch: Patch;
}) {
  const [draft, setDraft] = useState(() => ru(settings.markupPct));
  const [prevSaved, setPrevSaved] = useState(settings.markupPct);
  if (prevSaved !== settings.markupPct) {
    // Сохранили (или пришли новые настройки) — поле снова равно сохранённому.
    setPrevSaved(settings.markupPct);
    setDraft(ru(settings.markupPct));
  }
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const change = markupChange(draft, settings);
  const typed = change.error ? null : typedNumber(draft);
  const preview = useMemo(() => previewRows(settings, typed), [settings, typed]);
  const changed = changedPreview(preview);
  const ownCount = preview.filter((r) => r.own).length;
  const dirty = change.body !== null;
  const disabled = !canEditMoney || busy;

  const save = async () => {
    if (!change.body) return;
    setBusy(true);
    setError(null);
    const res = await onPatch(change.body, `Общая наценка: ${pctText(String(change.body.markup_pct))}`);
    setBusy(false);
    if (res.ok) setConfirming(false);
    else setError(res.error);
  };

  const floorBinds = typed !== null && typed < Number(settings.floorPct);

  return (
    <section className={`${CARD} p-5`}>
      <CardHeader icon={<FiPercent className={ICON} aria-hidden />} title="Общая наценка">
        {dirty && canEditMoney && (
          <>
            <button type="button" onClick={() => setDraft(ru(settings.markupPct))} disabled={busy} className={btn("plain", "lg")}>
              Отменить
            </button>
            <button
              type="button"
              onClick={() => {
                setError(null);
                setConfirming(true);
              }}
              disabled={busy}
              className={btn("primary", "lg")}
            >
              Сохранить
            </button>
          </>
        )}
      </CardHeader>
      <p className="mt-1 text-xs text-muted-2">
        Цена = себестоимость + наценка, делённая на цену кредита, с округлением вверх; минимум 1 кр. Действует для всех
        инструментов без своей наценки. Нижний порог {pctText(settings.floorPct)} — из «Настроек → Цены и наценка».
      </p>

      <div className="mt-4 flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-1">
          <label htmlFor="creative-markup" className="text-xs text-muted">
            Наценка, %
          </label>
          <input
            id="creative-markup"
            type="text"
            inputMode="decimal"
            autoComplete="off"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={disabled}
            aria-invalid={Boolean(change.error)}
            aria-describedby="creative-markup-hint"
            className={`${INPUT} w-32 tabular-nums`}
          />
        </div>
        <div id="creative-markup-hint" className="pb-2 text-[11px] text-muted-2">
          По умолчанию {pctText(settings.markupDefaultPct)}. Цена кредита:{" "}
          {settings.creditUsd ? `${usdText(settings.creditUsd)} (самый дешёвый пакет)` : "—"}.
        </div>
      </div>
      {change.error && <p className="mt-2 text-xs text-status-fail">{change.error}</p>}
      {!canEditMoney && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-muted">
          <FiLock className="h-3.5 w-3.5" aria-hidden />
          {SUPERUSER_TEXT}
        </p>
      )}
      {!settings.creditUsd && (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-status-wait">
          <FiAlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          Нет ни одного пакета с ценой — цену в кредитах не посчитать, инструменты не продаются.
        </p>
      )}
      {floorBinds && (
        <p className="mt-2 text-xs text-status-wait">
          Ниже порога {pctText(settings.floorPct)}: цена всё равно посчитается по порогу.
        </p>
      )}

      {dirty && (
        <div className="mt-4 rounded-xl border border-border bg-surface-2/50 p-3" aria-live="polite">
          <div className="text-xs text-muted">
            {changed.length > 0
              ? `После сохранения цена изменится у ${changed.length} из ${preview.length} инструментов (≈ — до округления сервера):`
              : "Цены в кредитах на примерах не изменятся: разница съедается округлением или порогом."}
            {ownCount > 0 && ` Со своей наценкой — ${ownCount}, их цена не меняется.`}
          </div>
          {changed.length > 0 && (
            <ul className="mt-2 space-y-1 text-sm tabular-nums">
              {changed.slice(0, PREVIEW_LIMIT).map((r) => (
                <li key={r.id} className="break-words text-foreground">
                  {previewLine(r)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {confirming && change.body && (
        <Dialog
          title={`Общая наценка ${pctText(String(change.body.markup_pct))}?`}
          subtitle="Цены инструментов без своей наценки изменятся для всех покупателей сразу."
          busy={busy}
          onClose={() => setConfirming(false)}
          onSubmit={() => void save()}
          error={error}
          footer={
            <>
              <button type="button" onClick={() => setConfirming(false)} disabled={busy} className={btn("plain", "lg")}>
                Отмена
              </button>
              <button type="submit" disabled={busy} className={btn("primary", "lg")}>
                {busy ? "Сохраняю…" : "Сохранить наценку"}
              </button>
            </>
          }
        >
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted">
            <li>
              Было {pctText(settings.markupPct)}, станет {pctText(String(change.body.markup_pct))}.
            </li>
            <li>
              Цена изменится у {changed.length} из {preview.length} инструментов
              {ownCount > 0 ? `; ${ownCount} со своей наценкой не меняются` : ""}.
            </li>
            {floorBinds && <li>Наценка ниже порога {pctText(settings.floorPct)} — фактически считаем по порогу.</li>}
            <li>Уже запущенные задачи стоят столько, сколько было на кнопке при запуске.</li>
          </ul>
          {changed.length > 0 && (
            <div>
              <div className="text-xs text-muted-2">Например:</div>
              <ul className="mt-1 space-y-1 text-sm tabular-nums text-foreground">
                {changed.slice(0, 5).map((r) => (
                  <li key={r.id}>{previewLine(r)}</li>
                ))}
              </ul>
            </div>
          )}
        </Dialog>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Инструменты                                                         */
/* ------------------------------------------------------------------ */

const SOURCE_TEXT = { global: "общая", own: "своя", floor: "порог" } as const;

/**
 * Таблица 15 инструментов: рубильник (сразу), своя наценка (пусто — общая)
 * с «Сохранить» в строке и пример «себестоимость → кредиты». Пока своя
 * наценка не сохранена — рядом «станет ≈ N кр».
 */
export function ToolsCard({
  settings,
  canEditMoney,
  onPatch,
  onFail,
}: {
  settings: Settings;
  canEditMoney: boolean;
  onPatch: Patch;
  onFail: (text: string) => void;
}) {
  // Только набранное и не сохранённое; нет ключа — в поле сохранённое значение.
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});

  const setDraft = (id: string, value: string | undefined) =>
    setDrafts((prev) => {
      const next = { ...prev };
      if (value === undefined) delete next[id];
      else next[id] = value;
      return next;
    });

  const run = async (t: ToolRow, body: Record<string, unknown>, okText: string, after?: () => void) => {
    setSaving((prev) => ({ ...prev, [t.id]: true }));
    const res = await onPatch(body, okText);
    setSaving((prev) => ({ ...prev, [t.id]: false }));
    if (res.ok) after?.();
    else onFail(`${t.name}: ${res.error}`);
  };

  const toggle = (t: ToolRow, on: boolean) =>
    void run(t, { tools: [{ id: t.id, enabled: on }] }, `${t.name}: ${on ? "включён" : "выключен"}`);

  const enabledCount = settings.tools.filter((t) => t.enabled).length;

  return (
    <section className={`${CARD} p-5`}>
      <CardHeader icon={<FiGrid className={ICON} aria-hidden />} title="Инструменты">
        <span className="text-xs text-muted">
          Включено {enabledCount} из {settings.tools.length}
        </span>
      </CardHeader>
      <p className="mt-1 text-xs text-muted-2">
        Выключенный инструмент на сайте показывается карточкой «Скоро», запустить его нельзя. Своя наценка — пусто,
        значит общая ({pctText(settings.markupPct)}). Пример — цена при настройках по умолчанию: столько стоит «от …» на
        карточке.
      </p>
      {!canEditMoney && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-muted">
          <FiLock className="h-3.5 w-3.5" aria-hidden />
          {SUPERUSER_TEXT} Включать и выключать инструменты могут все сотрудники.
        </p>
      )}

      {settings.tools.length === 0 ? (
        <p className="mt-4 text-sm text-muted">Сервер не прислал ни одного инструмента.</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted-2">
                <th scope="col" className="py-2 pr-3 font-medium">
                  Инструмент
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Включён
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Своя наценка, %
                </th>
                <th scope="col" className="py-2 pl-3 text-right font-medium">
                  Пример: себестоимость → цена
                </th>
              </tr>
            </thead>
            <tbody>
              {settings.tools.map((t) => {
                const typed = drafts[t.id];
                const value = typed ?? ownDraft(t);
                const change = typed === undefined ? { item: null, error: null } : ownChange(t, typed);
                const dirty = change.item !== null;
                const busy = saving[t.id] === true;
                const source = markupSource(t, settings);
                const pendingPct =
                  dirty && change.item
                    ? change.item.use_own_markup
                      ? Number(change.item.markup_pct)
                      : Number(settings.markupPct)
                    : null;
                const pending =
                  pendingPct === null
                    ? null
                    : estimateCredits(t.example.costUsd, pendingPct, settings.floorPct, settings.creditUsd);
                const inputId = `creative-own-${t.id}`;
                return (
                  <tr key={t.id} className={`border-b border-border align-top last:border-0 ${t.enabled ? "" : "opacity-70"}`}>
                    <td className="py-3 pr-3">
                      <div className="text-foreground">
                        <span className="mr-1.5 tabular-nums text-muted-2">{t.n}.</span>
                        {t.name}
                      </div>
                      <div className="mt-0.5 text-[11px] text-muted-2">
                        {categoryLabel(t.id)}
                        {t.kind && ` · ${KIND_LABEL[t.kind]}`}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <Switch
                        on={t.enabled}
                        label={t.enabled ? "да" : "нет"}
                        title={t.enabled ? `Выключить «${t.name}»` : `Включить «${t.name}»`}
                        disabled={busy}
                        onChange={(on) => toggle(t, on)}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <form
                        className="flex flex-wrap items-center gap-2"
                        onSubmit={(e) => {
                          e.preventDefault();
                          if (change.item) {
                            void run(
                              t,
                              { tools: [change.item] },
                              change.item.use_own_markup
                                ? `${t.name}: своя наценка ${pctText(String(change.item.markup_pct))}`
                                : `${t.name}: снова общая наценка`,
                              () => setDraft(t.id, undefined),
                            );
                          }
                        }}
                      >
                        <label htmlFor={inputId} className="sr-only">
                          Своя наценка «{t.name}», %
                        </label>
                        <input
                          id={inputId}
                          type="text"
                          inputMode="decimal"
                          autoComplete="off"
                          value={value}
                          placeholder={`общая ${ru(settings.markupPct)}`}
                          onChange={(e) => setDraft(t.id, e.target.value)}
                          disabled={!canEditMoney || busy}
                          aria-invalid={Boolean(change.error)}
                          className={`${INPUT} w-28 tabular-nums`}
                        />
                        {dirty && (
                          <>
                            <button type="submit" disabled={busy} className={btn("primary")}>
                              {busy ? "…" : "Сохранить"}
                            </button>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => setDraft(t.id, undefined)}
                              className={btn("plain")}
                            >
                              Отменить
                            </button>
                          </>
                        )}
                      </form>
                      {change.error ? (
                        <div className="mt-1 text-[11px] text-status-fail">{change.error}</div>
                      ) : (
                        <div className="mt-1">
                          <Badge
                            tone={source.source === "floor" ? "wait" : source.source === "own" ? "accent" : "muted"}
                            title={
                              source.source === "floor"
                                ? "Наценка ниже нижнего порога — цена считается по порогу"
                                : undefined
                            }
                          >
                            считается {pctText(source.pct)} · {SOURCE_TEXT[source.source]}
                          </Badge>
                        </div>
                      )}
                    </td>
                    <td className="py-3 pl-3 text-right">
                      <div className="text-[11px] text-muted-2">{t.example.label || "по умолчанию"}</div>
                      <div className="whitespace-nowrap tabular-nums">
                        <span className="text-muted">{usdText(t.example.costUsd)}</span>
                        <span className="text-muted-2"> → </span>
                        <span className="font-semibold text-foreground">{creditsText(t.example.credits)}</span>
                      </div>
                      {pending !== null && pending !== t.example.credits && (
                        <div className="text-[11px] tabular-nums text-accent">станет ≈{creditsText(pending)}</div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
