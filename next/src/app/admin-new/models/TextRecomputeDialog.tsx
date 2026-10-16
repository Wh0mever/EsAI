"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { FiAlertTriangle, FiArrowRight } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import { Badge, Skeleton, btn } from "../vstudio-showcase/parts";
import Dialog from "../studio-scenes/Dialog";
import {
  PRICING_SETTINGS_LINK,
  RECOMPUTE_COPY,
  RECOMPUTE_PATHS,
  STATUS_HINT,
  STATUS_LABEL,
  applicable,
  applyBody,
  appliedCount,
  coefText,
  defaultPicked,
  deltaText,
  errorText,
  keepPicked,
  legacyStudioText,
  parseRecompute,
  previewFromRefusal,
  recomputeUrl,
  ru,
  type Recompute,
  type RecomputeKind,
  type RecomputeRow,
} from "./modelsAdmin";

type Props = {
  /** Что пересчитываем: тарифы текста или тариф картинок Nano Banana в чате. */
  kind?: RecomputeKind;
  /** Ещё и эти модели, даже выключенные (только что добавленная). */
  ids: number[];
  /** Применено: сколько тарифов записано. */
  onApplied: (count: number) => void;
  onClose: () => void;
};

/**
 * «Пересчитать тарифы текста»: тариф = себестоимость OpenRouter (31 % вход +
 * 69 % выход) с наценкой ÷ цена кредита. «Пересчитать тариф картинок в чате»:
 * тариф Nano Banana = цена картинки по наценке × 1000 ÷ токены картинки — чат
 * берёт за неё токены × тариф, и иначе наценка до чата не доходит. Сначала
 * предпросмотр «было → станет», применяются только отмеченные — и только в
 * режиме «наценка». Сервер пересчитывает всё ещё раз: если цены за это время
 * сдвинулись, он присылает свежий предпросмотр, и ничего не пишется.
 */
export default function TextRecomputeDialog({ kind = "text", ids, onApplied, onClose }: Props) {
  const [tick, setTick] = useState(0);
  const [loaded, setLoaded] = useState<{ tick: number; error: string | null } | null>(null);
  const [preview, setPreview] = useState<Recompute | null>(null);
  const [picked, setPicked] = useState<ReadonlySet<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const idsKey = ids.join(",");

  const loading = loaded?.tick !== tick;

  useEffect(() => {
    let alive = true;
    (async () => {
      const list = idsKey ? idsKey.split(",").map(Number) : [];
      const res = await fetchData<unknown>(recomputeUrl(list, kind), "GET", undefined, true);
      if (!alive) return;
      const data = res.ok ? parseRecompute(res.data) : null;
      if (data) {
        setPreview(data);
        setPicked(defaultPicked(data));
      }
      setLoaded({ tick, error: data ? null : errorText(res, "Предпросмотр не посчитался") });
    })();
    return () => {
      alive = false;
    };
  }, [tick, idsKey, kind]);

  const ready = preview ? preview.rows.filter(applicable) : [];
  const chosen = ready.filter((r) => picked.has(r.id)).length;
  const canApply = Boolean(preview?.canApply) && chosen > 0 && !busy && !loading;

  const toggle = (id: number, on: boolean) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const apply = async () => {
    if (!preview || !canApply) return;
    setBusy(true);
    setError(null);
    const res = await fetchData<unknown>(RECOMPUTE_PATHS[kind], "POST", applyBody(preview, picked), true);
    setBusy(false);
    if (res.ok) {
      onApplied(appliedCount(res.data));
      onClose();
      return;
    }
    // 409 «цены изменились»: сервер приложил свежий предпросмотр — показываем его.
    const fresh = previewFromRefusal(res.data);
    if (fresh) {
      setPreview(fresh);
      setPicked((prev) => keepPicked(prev, fresh));
    }
    setError(errorText(res, "Не удалось применить тарифы"));
  };

  const copy = RECOMPUTE_COPY[kind];

  return (
    <Dialog
      title={copy.title}
      subtitle={copy.subtitle(preview?.tokens ?? (kind === "text" ? 2000 : 1450))}
      busy={busy}
      onClose={onClose}
      onSubmit={() => void apply()}
      error={error}
      wide
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy} className={btn("plain", "lg")}>
            Закрыть
          </button>
          <button
            type="submit"
            disabled={!canApply}
            title={preview && !preview.canApply ? preview.applyBlocked ?? undefined : undefined}
            className={btn("primary", "lg")}
          >
            {busy ? "Применяю…" : `Применить${chosen ? ` (${chosen})` : ""}`}
          </button>
        </>
      }
    >
      {loading && !preview ? (
        <div className="space-y-2" aria-busy="true">
          <Skeleton className="h-14" />
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
      ) : !preview ? (
        <div>
          <p className="text-sm text-status-fail">{loaded?.error}</p>
          <button type="button" onClick={() => setTick((t) => t + 1)} className={`${btn("plain")} mt-2`}>
            Повторить
          </button>
        </div>
      ) : (
        <Body
          kind={kind}
          preview={preview}
          picked={picked}
          busy={busy}
          onToggle={toggle}
          onAll={(on) => setPicked(on ? new Set(ready.map((r) => r.id)) : new Set())}
        />
      )}
    </Dialog>
  );
}

function Body({
  kind,
  preview,
  picked,
  busy,
  onToggle,
  onAll,
}: {
  kind: RecomputeKind;
  preview: Recompute;
  picked: ReadonlySet<number>;
  busy: boolean;
  onToggle: (id: number, on: boolean) => void;
  onAll: (on: boolean) => void;
}) {
  const ready = preview.rows.filter(applicable);
  const allOn = ready.length > 0 && ready.every((r) => picked.has(r.id));
  const settings = [
    `наценка ${preview.markupPct ? ru(preview.markupPct) : "—"} %`,
    `порог ${preview.floorPct ? ru(preview.floorPct) : "—"} %`,
    preview.basisLine ? `кредит: ${preview.basisLine}` : "",
  ].filter(Boolean);

  return (
    <>
      <p className="text-xs text-muted-2">
        Сохранённые настройки: {settings.join(" · ")}.{" "}
        <Link href={PRICING_SETTINGS_LINK} className="text-accent underline-offset-2 hover:underline">
          Изменить
        </Link>
      </p>
      {kind === "text" ? (
        <p className="text-xs text-muted-2">
          Картинки Nano Banana в чате тоже списываются по тарифу за токены, но здесь не пересчитываются: токены
          картинки OpenRouter берёт дороже текстовых. Их тариф — кнопка «{RECOMPUTE_COPY.chat_image.button}».
        </p>
      ) : (
        <p className="text-xs text-muted-2">
          Картинка в другое число токенов стоит пропорционально: длинный запрос — немного дороже. FLUX здесь нет —
          чат берёт его за картинку по себестоимости. Наценка меняется — тариф сам не следует: нажмите снова.
        </p>
      )}

      {!preview.canApply && preview.applyBlocked && (
        <p className="flex items-start gap-2 rounded-xl border border-status-wait/40 bg-status-wait/10 px-3 py-2 text-xs text-status-wait">
          <FiAlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>{preview.applyBlocked} Предпросмотр работает и сейчас.</span>
        </p>
      )}
      {!preview.catalogOk && (
        <p className="rounded-xl border border-status-wait/40 bg-status-wait/10 px-3 py-2 text-xs text-status-wait">
          Каталог OpenRouter сейчас не ответил — цен нет ни у одной модели. Попробуйте позже.
        </p>
      )}

      {preview.rows.length === 0 ? (
        <p className="text-sm text-muted">{RECOMPUTE_COPY[kind].empty}</p>
      ) : (
        <div>
          {ready.length > 0 && preview.canApply && (
            <label className="mb-2 inline-flex min-h-9 cursor-pointer items-center gap-2 text-xs text-muted">
              <input
                type="checkbox"
                className="h-4 w-4 accent-accent"
                checked={allOn}
                onChange={(e) => onAll(e.target.checked)}
                disabled={busy}
              />
              Отметить все, что пересчитаются ({ready.length})
            </label>
          )}
          <ul className="space-y-2">
            {preview.rows.map((row) => (
              <Line
                key={row.id}
                unit={RECOMPUTE_COPY[kind].unit}
                row={row}
                checkable={preview.canApply && applicable(row)}
                checked={picked.has(row.id)}
                busy={busy}
                onToggle={onToggle}
              />
            ))}
          </ul>
        </div>
      )}

      <p className="text-[11px] text-muted-2">
        Записываются только отмеченные строки. Прежние тарифы остаются в журнале действий: возврат режима
        «по-старому» их не вернёт — вернуть можно вручную в строке модели.
      </p>
    </>
  );
}

function Line({
  unit,
  row,
  checkable,
  checked,
  busy,
  onToggle,
}: {
  unit: string;
  row: RecomputeRow;
  checkable: boolean;
  checked: boolean;
  busy: boolean;
  onToggle: (id: number, on: boolean) => void;
}) {
  const delta = deltaText(row.deltaPct);
  const legacy = legacyStudioText(row);
  const tone = row.status === "ok" ? "accent" : row.status === "unchanged" ? "muted" : "wait";
  const id = `recompute-${row.id}`;
  return (
    <li className="flex items-start gap-3 rounded-xl border border-border px-3 py-2.5">
      <input
        id={id}
        type="checkbox"
        className="mt-1 h-4 w-4 shrink-0 accent-accent disabled:opacity-40"
        checked={checkable && checked}
        disabled={!checkable || busy}
        onChange={(e) => onToggle(row.id, e.target.checked)}
        aria-label={`Применить новый тариф «${row.name}»`}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <label htmlFor={id} className="break-words text-sm font-medium text-foreground">
            {row.name}
          </label>
          <Badge tone={tone} title={STATUS_HINT[row.status]}>
            {STATUS_LABEL[row.status]}
          </Badge>
          {!row.isActive && <Badge tone="muted">выключена</Badge>}
          {row.markupSource === "model" && row.markupPct && (
            <Badge tone="muted" title="У модели своя наценка">
              наценка {ru(row.markupPct)} %
            </Badge>
          )}
        </div>
        <div className="mt-0.5 break-all font-mono text-[11px] text-muted-2">{row.openrouterId}</div>
        {row.priceText && <div className="mt-0.5 text-xs text-muted">{row.priceText}</div>}
        <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm tabular-nums">
          <span className="inline-flex items-center gap-1.5">
            <span className="text-muted-2">тариф</span>
            <span className="text-muted">{coefText(row.oldCoefficient)}</span>
            {row.newCoefficient !== null && (
              <>
                <FiArrowRight className="h-3.5 w-3.5 text-muted-2" aria-label="станет" />
                <span className="font-semibold text-foreground">{coefText(row.newCoefficient)}</span>
              </>
            )}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="text-muted-2">{unit}</span>
            <span className="text-muted">{row.oldCredits ?? "—"} кр</span>
            {row.newCredits !== null && (
              <>
                <FiArrowRight className="h-3.5 w-3.5 text-muted-2" aria-label="станет" />
                <span className="font-semibold text-foreground">{row.newCredits} кр</span>
              </>
            )}
            {delta && <span className="text-xs text-muted-2">({delta})</span>}
          </span>
        </div>
        {legacy && <div className="mt-1 text-xs text-muted-2">{legacy}</div>}
      </div>
    </li>
  );
}
