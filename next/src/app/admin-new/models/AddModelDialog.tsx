"use client";

import { useEffect, useRef, useState, type RefObject } from "react";
import { FiArrowLeft, FiSearch } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import { Badge, INPUT_LG, Skeleton, btn, chip } from "../vstudio-showcase/parts";
import Dialog from "../studio-scenes/Dialog";
import {
  CATALOG_KINDS,
  CATALOG_QUERY_MAX,
  KIND_LABEL,
  MODELS_PATH,
  NAME_MAX,
  TEXT_CATEGORIES,
  addBody,
  addProblem,
  catalogUrl,
  errorText,
  existingId,
  kindOf,
  parseAdded,
  parseCatalog,
  type Added,
  type Catalog,
  type CatalogEntry,
  type CatalogKind,
} from "./modelsAdmin";

/** Пауза после последней буквы, прежде чем спрашивать каталог. */
const SEARCH_DELAY_MS = 300;

const CATALOG_NAME: Record<string, string> = { video: "видео", text: "текста и картинок" };

type Props = {
  /** Модель добавлена: строка встаёт в список. */
  onAdded: (added: Added) => void;
  /** Модель уже есть — показать её строку в списке. */
  onShow: (id: number) => void;
  /** Добавили текстовую — сразу посчитать ей тариф от себестоимости. */
  onRecompute: (id: number) => void;
  onClose: () => void;
};

/**
 * «Добавить модель»: поиск по каталогам OpenRouter (видео — /videos/models,
 * текст и картинки — /models) по ID или названию. Модель встаёт выключенной,
 * с тарифом 1 и без видеостудии: владелец проверяет цену и включает её сам.
 */
export default function AddModelDialog({ onAdded, onShow, onRecompute, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<CatalogKind>("");
  const [found, setFound] = useState<{ key: string; data: Catalog } | null>(null);
  const [failed, setFailed] = useState<{ key: string; text: string } | null>(null);
  const [picked, setPicked] = useState<CatalogEntry | null>(null);
  const [name, setName] = useState("");
  const [category, setCategory] = useState("chat");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflictId, setConflictId] = useState<number | null>(null);
  const [added, setAdded] = useState<Added | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const tooLong = query.trim().length > CATALOG_QUERY_MAX;
  const key = `${kind}|${query.trim()}`;

  useEffect(() => {
    if (tooLong) return;
    let alive = true;
    const timer = setTimeout(async () => {
      const res = await fetchData<unknown>(catalogUrl(query, kind), "GET", undefined, true);
      if (!alive) return;
      const data = res.ok ? parseCatalog(res.data) : null;
      if (data) setFound({ key, data });
      else setFailed({ key, text: errorText(res, "Каталог OpenRouter не ответил") });
    }, SEARCH_DELAY_MS);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [key, query, kind, tooLong]);

  // Сменился шаг окна — фокус в его главное поле: кнопка, на которой он стоял, исчезла.
  const step = added ? "done" : picked ? "confirm" : "search";
  useEffect(() => {
    try {
      if (step === "confirm") nameRef.current?.focus({ preventScroll: true });
      if (step === "search") searchRef.current?.focus({ preventScroll: true });
    } catch {}
  }, [step]);

  const pick = (entry: CatalogEntry) => {
    setPicked(entry);
    setName(entry.name);
    setCategory(entry.category);
    setError(null);
    setConflictId(null);
  };

  const back = () => {
    setPicked(null);
    setError(null);
    setConflictId(null);
  };

  const add = async () => {
    if (!picked || busy) return;
    const problem = addProblem(picked, name);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    setConflictId(null);
    const res = await fetchData<unknown>(MODELS_PATH, "POST", addBody(picked, name, category), true);
    setBusy(false);
    const result = res.ok ? parseAdded(res.data) : null;
    if (!result) {
      setError(
        res.ok
          ? "Модель добавлена, но ответ сервера не разобрать — закройте окно и обновите список."
          : errorText(res, "Не удалось добавить модель"),
      );
      if (res.status === 409) setConflictId(existingId(res.data));
      return;
    }
    setAdded(result);
    onAdded(result);
  };

  const submit = () => {
    if (step === "confirm") void add();
    else if (step === "done") onClose();
  };

  const footer =
    step === "done" && added ? (
      <>
        {kindOf(added.model.category) === "text" && (
          <button type="button" onClick={() => onRecompute(added.model.id)} className={btn("plain", "lg")}>
            Посчитать тариф
          </button>
        )}
        <button type="submit" className={btn("primary", "lg")}>
          Готово
        </button>
      </>
    ) : step === "confirm" ? (
      <>
        {conflictId !== null && (
          <button type="button" onClick={() => onShow(conflictId)} className={btn("plain", "lg")}>
            Показать в списке
          </button>
        )}
        <button type="button" onClick={back} disabled={busy} className={btn("plain", "lg")}>
          <FiArrowLeft className="h-4 w-4" aria-hidden />
          Назад
        </button>
        <button type="submit" disabled={busy} className={btn("primary", "lg")}>
          {busy ? "Добавляю…" : "Добавить выключенной"}
        </button>
      </>
    ) : (
      <button type="button" onClick={onClose} className={btn("plain", "lg")}>
        Закрыть
      </button>
    );

  return (
    <Dialog
      title="Добавить модель"
      subtitle="Из каталога OpenRouter. Модель встанет выключенной: проверьте цену и включите её в списке."
      busy={busy}
      onClose={onClose}
      onSubmit={submit}
      error={error}
      footer={footer}
      wide
    >
      {step === "done" && added ? (
        <Done added={added} />
      ) : step === "confirm" && picked ? (
        <Confirm
          entry={picked}
          name={name}
          category={category}
          busy={busy}
          nameRef={nameRef}
          onName={setName}
          onCategory={setCategory}
        />
      ) : (
        <Search
          query={query}
          kind={kind}
          tooLong={tooLong}
          found={found?.key === key ? found.data : null}
          stale={found !== null && found.key !== key ? found.data : null}
          failed={failed?.key === key ? failed.text : null}
          searchRef={searchRef}
          onQuery={setQuery}
          onKind={setKind}
          onPick={pick}
          onShow={onShow}
        />
      )}
    </Dialog>
  );
}

function Search({
  query,
  kind,
  tooLong,
  found,
  stale,
  failed,
  searchRef,
  onQuery,
  onKind,
  onPick,
  onShow,
}: {
  query: string;
  kind: CatalogKind;
  tooLong: boolean;
  found: Catalog | null;
  /** Прошлый ответ, пока идёт новый поиск, — чтобы список не мигал. */
  stale: Catalog | null;
  failed: string | null;
  searchRef: RefObject<HTMLInputElement | null>;
  onQuery: (q: string) => void;
  onKind: (k: CatalogKind) => void;
  onPick: (entry: CatalogEntry) => void;
  onShow: (id: number) => void;
}) {
  const shown = found ?? stale;
  const searching = !found && !failed && !tooLong;
  return (
    <>
      <div>
        <label htmlFor="catalog-q" className="text-sm text-muted">
          ID или название модели
        </label>
        <div className="relative mt-1.5">
          <FiSearch className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-2" aria-hidden />
          <input
            id="catalog-q"
            ref={searchRef}
            type="text"
            value={query}
            onChange={(e) => onQuery(e.target.value)}
            placeholder="seedance, bytedance/seedance-2.0-mini, gpt-5…"
            autoComplete="off"
            spellCheck={false}
            className={`${INPUT_LG} block w-full pl-9`}
          />
        </div>
        <div role="group" aria-label="Вид модели" className="mt-2 flex flex-wrap gap-2">
          {CATALOG_KINDS.map((k) => (
            <button
              key={k.key || "all"}
              type="button"
              aria-pressed={kind === k.key}
              onClick={() => onKind(k.key)}
              className={`${chip(kind === k.key)} min-h-9`}
            >
              {k.label}
            </button>
          ))}
        </div>
      </div>

      {tooLong && <p className="text-sm text-status-fail">Запрос длиннее {CATALOG_QUERY_MAX} символов.</p>}
      {failed && <p className="text-sm text-status-fail">{failed}</p>}
      {shown && shown.unavailable.length > 0 && (
        <p className="rounded-xl border border-status-wait/40 bg-status-wait/10 px-3 py-2 text-xs text-status-wait">
          Не ответил каталог {shown.unavailable.map((c) => CATALOG_NAME[c] ?? c).join(" и ")} — модели оттуда сейчас
          не найти. Попробуйте позже.
        </p>
      )}

      <div aria-live="polite" aria-busy={searching}>
        {!shown && searching ? (
          <div className="space-y-2">
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </div>
        ) : shown && shown.results.length === 0 ? (
          <p className="text-sm text-muted">
            Ничего не нашлось{query.trim() ? ` по «${query.trim()}»` : ""}. Проверьте ID — как на openrouter.ai.
          </p>
        ) : shown ? (
          <>
            <ul className={`space-y-2 transition-opacity ${found ? "" : "opacity-60"}`}>
              {shown.results.map((entry) => (
                <CatalogRow key={entry.openrouterId} entry={entry} onPick={onPick} onShow={onShow} />
              ))}
            </ul>
            {shown.truncated && (
              <p className="mt-2 text-xs text-muted-2">
                Показаны первые {shown.results.length} из {shown.count} — уточните запрос.
              </p>
            )}
          </>
        ) : null}
      </div>
    </>
  );
}

function CatalogRow({
  entry,
  onPick,
  onShow,
}: {
  entry: CatalogEntry;
  onPick: (entry: CatalogEntry) => void;
  onShow: (id: number) => void;
}) {
  const cost =
    entry.costText ?? (entry.kind === "image" ? "себестоимость введёте после добавления" : "цены нет в каталоге");
  const price =
    entry.priceMarkup === null
      ? ""
      : entry.kind === "text"
        ? ` · сообщение после пересчёта: ${entry.priceMarkup} кр`
        : ` · при наценке: ${entry.priceMarkup} кр`;
  const existing = entry.exists && entry.modelId !== null ? entry.modelId : null;
  return (
    <li>
      <button
        type="button"
        onClick={() => (existing !== null ? onShow(existing) : onPick(entry))}
        className="block w-full cursor-pointer rounded-xl border border-border bg-surface-2/40 px-3 py-2.5 text-left transition-colors hover:border-accent/60"
      >
        <span className="flex flex-wrap items-center gap-1.5">
          <span className="break-words text-sm font-medium text-foreground">{entry.name}</span>
          <Badge tone="muted">{KIND_LABEL[entry.kind]}</Badge>
          {entry.exists && (
            <Badge tone="accent" title="Строка уже есть — нажмите, чтобы показать её в списке">
              {entry.isActive === false ? "уже есть · выключена" : "уже есть"}
            </Badge>
          )}
          {entry.kind === "video" && !entry.vstudioSupported && (
            <Badge tone="muted" title="Видеостудия пока не знает эту модель — показать её можно только в чате">
              только чат
            </Badge>
          )}
        </span>
        <span className="mt-0.5 block break-all font-mono text-[11px] text-muted-2">{entry.openrouterId}</span>
        <span className="mt-0.5 block text-xs text-muted">
          {cost}
          {price}
        </span>
        {existing !== null && <span className="mt-0.5 block text-xs text-accent">Показать в списке →</span>}
      </button>
    </li>
  );
}

function Confirm({
  entry,
  name,
  category,
  busy,
  nameRef,
  onName,
  onCategory,
}: {
  entry: CatalogEntry;
  name: string;
  category: string;
  busy: boolean;
  nameRef: RefObject<HTMLInputElement | null>;
  onName: (name: string) => void;
  onCategory: (category: string) => void;
}) {
  const facts = [
    KIND_LABEL[entry.kind],
    entry.costText ? `себестоимость ${entry.costText}` : "",
    entry.priceMarkup !== null
      ? entry.kind === "text"
        ? `после пересчёта тарифа ${entry.coefficient ? entry.coefficient.replace(".", ",") : "—"} кр за 1000 токенов`
        : `при наценке ${entry.priceMarkup} кр`
      : "",
  ].filter(Boolean);
  return (
    <>
      <div className="rounded-xl border border-border bg-surface-2 px-3 py-2.5">
        <div className="break-words text-sm font-medium text-foreground">{entry.fullName || entry.name}</div>
        <div className="mt-0.5 break-all font-mono text-[11px] text-muted-2">{entry.openrouterId}</div>
        <div className="mt-1 text-xs text-muted">{facts.join(" · ")}</div>
        {entry.description && <p className="mt-2 text-xs text-muted-2">{entry.description}</p>}
      </div>

      <label className="block text-sm">
        <span className="text-muted">Название в списке</span>
        <input
          ref={nameRef}
          type="text"
          value={name}
          maxLength={NAME_MAX}
          onChange={(e) => onName(e.target.value)}
          disabled={busy}
          className={`${INPUT_LG} mt-1.5 block w-full`}
        />
        <span className="mt-1 block text-xs text-muted-2">
          Пусто — название из каталога. Занятое название сервер дополнит «(2)».
        </span>
      </label>

      {entry.kind === "text" ? (
        <label className="block text-sm">
          <span className="text-muted">Категория</span>
          <select
            value={category}
            onChange={(e) => onCategory(e.target.value)}
            disabled={busy}
            className={`${INPUT_LG} mt-1.5 block w-full`}
          >
            {TEXT_CATEGORIES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <p className="text-sm text-muted">
          Категория: <span className="text-foreground">{entry.kind === "video" ? "Видео" : "Изображения"}</span>
        </p>
      )}

      <ul className="list-disc space-y-1 pl-5 text-xs text-muted-2">
        <li>Модель встанет выключенной, с тарифом 1 и без видеостудии — покупатели её не увидят, пока вы её не включите.</li>
        {entry.kind === "text" && (
          <li>Тариф текста задайте сами или кнопкой «Пересчитать тарифы текста» — она посчитает его от себестоимости.</li>
        )}
        {entry.kind === "image" && (
          <li>Себестоимость картинки в каталоге не указана — введите её в строке модели перед включением.</li>
        )}
        {entry.kind === "video" && !entry.vstudioSupported && (
          <li>Видеостудия пока не знает эту модель: показать её можно только в чате.</li>
        )}
      </ul>
    </>
  );
}

function Done({ added }: { added: Added }) {
  return (
    <>
      <p className="text-sm text-foreground">
        Модель «{added.model.name}» добавлена в список выключенной.
      </p>
      {added.warnings.length > 0 && (
        <ul className="space-y-2">
          {added.warnings.map((w) => (
            <li
              key={w}
              className="rounded-xl border border-status-wait/40 bg-status-wait/10 px-3 py-2 text-xs text-status-wait"
            >
              {w}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
