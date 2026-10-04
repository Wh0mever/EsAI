"use client";

import { useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ERROR_RU } from "@/lib/creators/errors";
import { fmtDate, fmtDateTime, isHttpUrl } from "@/lib/creators/format";
import type { CrError } from "@/lib/creators/types";
import { STATUS_TONE, SU_ONLY, labelFrom, type Tone } from "./labels";
import { useCreatorsRole } from "./role";

/* ------------------------------------------------------------------ */
/* Классы                                                              */
/* ------------------------------------------------------------------ */

const INPUT_FRAME =
  "rounded-lg border border-border bg-surface-2 px-3 text-sm text-foreground outline-none focus:border-accent disabled:opacity-60";
export const INPUT = `${INPUT_FRAME} py-2`;
/** Поле в строке фильтров — той же высоты, что чипы. */
export const INPUT_SM = `${INPUT_FRAME} py-1.5`;

// Размер и цвет кнопки собираются из отдельных частей: два класса на одно
// свойство (px-2.5 и px-3) в одной строке Tailwind разрешает по порядку в CSS,
// а не по порядку в className.
const BTN_FRAME = "rounded-lg border transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-50";
const BTN_SIZE = { sm: "px-2.5 py-1 text-xs", md: "px-3 py-1.5 text-xs", lg: "px-4 py-2 text-sm" } as const;
const BTN_TONE = {
  plain: "border-border text-muted enabled:hover:border-accent enabled:hover:text-accent",
  on: "border-accent text-accent",
  ok: "border-status-ok/40 text-status-ok enabled:hover:bg-status-ok/10",
  danger: "border-status-fail/40 text-status-fail enabled:hover:bg-status-fail/10",
} as const;

export const btn = (tone: keyof typeof BTN_TONE = "plain", size: keyof typeof BTN_SIZE = "sm"): string =>
  `${BTN_FRAME} ${BTN_SIZE[size]} ${BTN_TONE[tone]}`;

export const BTN = btn();
export const BTN_OK = btn("ok");
export const BTN_DANGER = btn("danger");
export const BTN_MD = btn("plain", "md");
export const BTN_OK_MD = btn("ok", "md");
export const BTN_DANGER_MD = btn("danger", "md");
export const BTN_LG = btn("plain", "lg");
/** Выбранный вариант в ряду кнопок (заготовки количества). */
export const BTN_ON = btn("on");

const PRIMARY_FRAME =
  "rounded-xl px-4 py-2 text-sm font-semibold transition-opacity cursor-pointer enabled:hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50";
export const BTN_PRIMARY = `${PRIMARY_FRAME} bg-accent text-on-accent`;
export const BTN_PRIMARY_DANGER = `${PRIMARY_FRAME} bg-rose-600 text-white`;

export const CARD = "rounded-2xl border border-border bg-surface p-4 sm:p-6";
export const TH = "px-3 py-3 font-medium";
export const TD = "px-3 py-3 align-top";
export const THEAD_ROW = "border-b border-border text-left text-xs uppercase tracking-wide text-muted-2";
export const ROW = "border-b border-border last:border-0";

/* ------------------------------------------------------------------ */
/* Тексты и формат                                                     */
/* ------------------------------------------------------------------ */

/**
 * В панели сервер говорит про того, над кем действие, а его тексты написаны
 * для самого человека («У вас уже есть заявка…»). Эти три переформулируем.
 */
const ADMIN_ERROR: Record<string, string> = {
  withdrawal_open: "У креатора уже есть другая заявка на вывод в работе",
  already_creator: "Этот пользователь уже участник программы EsAI Creators",
  self: "Креатора нельзя закрепить за самим собой",
};

/** Текст отказа: русское сообщение сервера; у validation — тексты полей. */
export function errText(error: CrError | null | undefined): string {
  if (!error) return "";
  if (error.code === "validation" && error.fields) {
    const parts = Object.values(error.fields).filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  return ADMIN_ERROR[error.code] || error.message || ERROR_RU[error.code] || ERROR_RU.unknown;
}

export const dt = (iso: string | null | undefined): string => (iso ? fmtDateTime(iso, "ru") : "—");
export const d = (iso: string | null | undefined): string => (iso ? fmtDate(iso, "ru") : "—");
export const nf = (n: number | null | undefined): string => Number(n ?? 0).toLocaleString("ru-RU");
export const dash = (value: string | number | null | undefined): string =>
  value === null || value === undefined || value === "" ? "—" : String(value);

/** Только цифры: id в поле формы и в адресной строке. */
export const isDigits = (value: string): boolean => /^\d+$/.test(value);

/* ------------------------------------------------------------------ */
/* Мелкие блоки                                                        */
/* ------------------------------------------------------------------ */

export function ErrorBox({ error, className = "" }: { error: CrError | string | null | undefined; className?: string }) {
  const text = typeof error === "string" ? error : errText(error);
  if (!text) return null;
  return (
    <div className={`rounded-xl border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300 ${className}`}>
      {text}
    </div>
  );
}

export function OkBox({ children, className = "" }: { children: ReactNode; className?: string }) {
  if (!children) return null;
  return (
    <div className={`rounded-xl border border-status-ok/40 bg-status-ok/10 px-3 py-2 text-sm text-status-ok ${className}`}>
      {children}
    </div>
  );
}

const TONE_CLASS: Record<Tone, string> = {
  wait: "border-status-wait/30 bg-status-wait/10 text-status-wait",
  ok: "border-status-ok/30 bg-status-ok/10 text-status-ok",
  fail: "border-status-fail/30 bg-status-fail/10 text-status-fail",
  muted: "border-border bg-surface-2 text-muted",
};

export function Badge({ tone = "muted", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium ${TONE_CLASS[tone]}`}
    >
      {children}
    </span>
  );
}

/** Плашка статуса: подпись из таблицы раздела, цвет — по смыслу статуса. */
export function StatusPill({ table, status }: { table: Record<string, string>; status: string }) {
  return <Badge tone={STATUS_TONE[status] ?? "muted"}>{labelFrom(table, status)}</Badge>;
}

export function Skeleton({ className = "h-72" }: { className?: string }) {
  return <div className={`animate-pulse rounded-2xl bg-surface-2 ${className}`} />;
}

export function PageTitle({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div>
      <h2 className="text-lg font-semibold">{title}</h2>
      {hint ? <p className="mt-1 text-sm text-muted">{hint}</p> : null}
    </div>
  );
}

/** Таблица шире экрана прокручивается внутри своей рамки — страница вбок не едет. */
export function TableWrap({ minWidth, children }: { minWidth: number; children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-border bg-surface">
      <table className="w-full text-sm" style={{ minWidth }}>
        {children}
      </table>
    </div>
  );
}

export function EmptyRow({ colSpan, children }: { colSpan: number; children: ReactNode }) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-4 py-8 text-center text-muted">
        {children}
      </td>
    </tr>
  );
}

/* ------------------------------------------------------------------ */
/* Фильтры                                                             */
/* ------------------------------------------------------------------ */

const CHIP = "rounded-lg border px-3 py-1.5 text-xs transition-colors cursor-pointer";
const CHIP_ON = "border-accent bg-accent/10 text-accent";
const CHIP_OFF = "border-border text-muted hover:text-foreground";

export function Chips<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { key: T; label: string }[];
  value: T;
  onChange: (key: T) => void;
}) {
  return (
    <>
      {options.map((option) => (
        <button
          key={option.key}
          type="button"
          onClick={() => onChange(option.key)}
          className={`${CHIP} ${value === option.key ? CHIP_ON : CHIP_OFF}`}
        >
          {option.label}
        </button>
      ))}
    </>
  );
}

/** Чип-переключатель («Подозрительные», «Только действующие»). */
export function ToggleChip({ on, onChange, children }: { on: boolean; onChange: (on: boolean) => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={() => onChange(!on)}
      className={`${CHIP} ${on ? CHIP_ON : CHIP_OFF}`}
    >
      {on ? "✓ " : ""}
      {children}
    </button>
  );
}

export function SearchForm({ placeholder, onSearch }: { placeholder: string; onSearch: (q: string) => void }) {
  const [query, setQuery] = useState("");
  return (
    <form
      className="flex w-full items-center gap-2 sm:ml-auto sm:w-auto"
      onSubmit={(e) => {
        e.preventDefault();
        onSearch(query.trim());
      }}
    >
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={placeholder}
        className={`${INPUT_SM} min-w-0 flex-1 sm:w-64 sm:flex-none`}
      />
      <button type="submit" className={BTN_MD}>
        Найти
      </button>
    </form>
  );
}

/**
 * Фильтр из адресной строки (?creator=12): по ссылке «Все →» из профиля
 * вкладка открывается уже отфильтрованной. Не число — фильтра нет.
 */
export function useIdParam(name: string): string {
  const raw = (useSearchParams().get(name) ?? "").trim();
  return isDigits(raw) ? raw : "";
}

/** Плашка «Creator #12 ✕»: показывает фильтр из адресной строки и снимает его. */
export function IdParamChip({ name, label }: { name: string; label: string }) {
  const value = useIdParam(name);
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  if (!value) return null;

  const clear = () => {
    const rest = new URLSearchParams(search.toString());
    rest.delete(name);
    const tail = rest.toString();
    router.replace(tail ? `${pathname}?${tail}` : pathname);
  };

  return (
    <span className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs ${CHIP_ON}`}>
      {label} #{value}
      <button type="button" onClick={clear} title="Снять фильтр" className="cursor-pointer text-accent hover:text-foreground">
        ✕
      </button>
    </span>
  );
}

export function MoreButton({
  shown,
  total,
  loading,
  onMore,
  error,
}: {
  shown: number;
  total: number;
  loading: boolean;
  onMore: () => void;
  error?: CrError | null;
}) {
  if (shown >= total) return null;
  return (
    <div className="flex flex-col items-center gap-2">
      <ErrorBox error={error} />
      <button
        type="button"
        onClick={onMore}
        disabled={loading}
        className="cursor-pointer rounded-xl border border-border px-6 py-2.5 text-sm text-muted transition-colors hover:border-accent hover:text-accent disabled:cursor-default disabled:opacity-50"
      >
        {loading ? "Загружаю…" : `Ещё (показано ${nf(shown)} из ${nf(total)})`}
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Ссылки и копирование                                                */
/* ------------------------------------------------------------------ */

export function CreatorLink({ id, name }: { id: number | null | undefined; name: string | null | undefined }) {
  if (!id) return <span className="text-muted-2">{dash(name)}</span>;
  return (
    <Link href={`/admin-new/creators/${id}`} className="font-medium text-foreground hover:text-accent hover:underline">
      {name || `#${id}`}
    </Link>
  );
}

/**
 * Ссылка, которую прислал человек (соцсеть, публикация, пример работы).
 * Открываем только http(s): всё остальное показываем текстом, а не ссылкой.
 */
export function ExtLink({ href, children, className = "" }: { href: string | null | undefined; children?: ReactNode; className?: string }) {
  const url = String(href ?? "").trim();
  if (!url) return <span className="text-muted-2">—</span>;
  if (!isHttpUrl(url)) return <span className={`break-all ${className}`}>{children ?? url}</span>;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className={`break-all text-accent hover:underline ${className}`}>
      {children ?? url}
    </a>
  );
}

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Буфер недоступен (http, старый webview) — пробуем через textarea.
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}

export function CopyButton({ text, label = "Копировать" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  if (!text) return null;
  return (
    <button
      type="button"
      className={BTN}
      onClick={async () => {
        if (await copyText(text)) {
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        }
      }}
    >
      {copied ? "Скопировано" : label}
    </button>
  );
}

/** Длинная строка (адрес, TXID) целиком, моноширинно, с переносом и кнопкой копирования. */
export function CopyValue({ value }: { value: string | null | undefined }) {
  const text = String(value ?? "");
  if (!text) return <span className="text-muted-2">—</span>;
  return (
    <div className="flex flex-col items-start gap-1">
      <span className="break-all font-mono text-xs">{text}</span>
      <CopyButton text={text} />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Права                                                               */
/* ------------------------------------------------------------------ */

/**
 * Кнопка денежного или структурного действия. Сотруднику её видно, но она
 * выключена: понятно, что действие есть и кто его делает. Решает сервер —
 * он ответит 403 superuser_required, даже если кнопку включить руками.
 */
export function SuButton({ className = BTN, disabled, title, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  const { isSuperuser } = useCreatorsRole();
  return (
    <button
      type="button"
      {...rest}
      disabled={!isSuperuser || disabled}
      title={isSuperuser ? title : SU_ONLY}
      className={className}
    >
      {children}
    </button>
  );
}

/** Подпись под выключенными кнопками — только для сотрудника. */
export function SuCaption({ className = "" }: { className?: string }) {
  const { role } = useCreatorsRole();
  if (role !== "staff") return null;
  return <p className={`text-[11px] text-muted-2 ${className}`}>{SU_ONLY}</p>;
}
