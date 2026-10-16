"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiAlertCircle, FiEdit2, FiLogIn, FiMenu, FiX, FiZap } from "react-icons/fi";
import { rememberReturnPath } from "@/tools/authNext";
import { VS_FOCUS, VS_ICON_BTN, VS_PILL, VS_PILL_ON, VS_SECTION, vx } from "@/components/vstudio/ui/skin";
import { CS_NOTE_FAIL, CS_TALL_HIT } from "./ui/cartoonSkin";
import type { Project } from "./cartoonTypes";

/**
 * Верх мультстудии в оболочке видеостудии (VStudioShell).
 *
 * - CartoonHeader — компьютер (≥1024): название открытого мультфильма с
 *   переименованием и баланс.
 * - CartoonTopBar — телефон, планшет и Telegram: ☰ (мои мультфильмы
 *   шторкой), название, баланс.
 * - BalancePill — баланс со ссылкой на пополнение; у гостя вместо него «Войти».
 * - ErrorBanner — отказ или сбой над лентой.
 *
 * Свои компоненты, а не StudioTopBar видеостудии: тот читает её стор, и импорт
 * притянул бы стор в мультстудию целиком. Классы — те же, из skin.ts.
 */

/** Пополнение — та же страница, куда ведёт окно «не хватает кредитов». */
const TOPUP_HREF = "/pricing/studio";

/** Длина названия — как у хука (renameMovie) и у проектов видеостудии. */
export const MAX_TITLE_CHARS = 140;

const fmt = (n: number) => Math.max(0, Math.round(n)).toLocaleString("ru-RU");

/** Вход с возвратом в студию: путь ещё и в cookie — его переживает соц-вход. */
export function signInHref(back: string): string {
  return `/auth/signin?next=${encodeURIComponent(back)}`;
}

/* ------------------------------------------------------------------ */
/* Баланс                                                              */
/* ------------------------------------------------------------------ */

export type BalancePillProps = {
  /** chip — строка над лентой, rail — низ колонки, compact — колонка значков 64 px. */
  variant?: "chip" | "rail" | "compact";
  loading: boolean;
  authed: boolean;
  balance: number | null;
  /** Баланс не пришёл (сбой профиля): «—» вместо вечного «…». */
  failed?: boolean;
  /** Куда вернуть гостя после входа. */
  back: string;
};

export function BalancePill({ variant = "chip", loading, authed, balance, failed = false, back }: BalancePillProps) {
  const { t } = useTranslation("common");

  if (loading) {
    // Заглушка той же величины: когда придут баланс или «Войти», соседи не сдвинутся.
    return (
      <span
        aria-hidden="true"
        className={vx(
          "vs-film shrink-0",
          variant === "compact"
            ? "h-12 w-11 rounded-2xl"
            : variant === "rail"
              ? "h-11 w-full rounded-full md:h-10"
              : "h-9 w-24 rounded-full md:h-10",
        )}
      />
    );
  }

  if (!authed) {
    const signin = t("studio_ui.shell_signin", { defaultValue: "Войти" });
    // Вход — не главное действие экрана (оно в доке), поэтому кнопка тихая, с золотой кромкой.
    return (
      <a
        href={signInHref(back)}
        onClick={() => rememberReturnPath(back)}
        className={
          variant === "compact"
            ? vx(VS_ICON_BTN, VS_PILL_ON)
            : vx(VS_PILL, VS_PILL_ON, "max-md:h-11 md:!h-10", variant === "rail" && "w-full justify-center")
        }
        title={signin}
        aria-label={variant === "compact" ? signin : undefined}
      >
        <FiLogIn className={variant === "compact" ? "text-lg" : "shrink-0"} aria-hidden="true" />
        {variant !== "compact" && signin}
      </a>
    );
  }

  const unknown = failed ? "—" : "…";
  const amount = balance == null ? unknown : t("studio_ui.shell_balance", { defaultValue: "{{n}} кр", n: fmt(balance) });
  const topup = t("studio_ui.rail_topup", { defaultValue: "Пополнить" });

  if (variant === "compact") {
    // Колонка 64 px: значок и короткое число, сумма целиком — в подсказке.
    const short = balance == null ? unknown : balance >= 10000 ? `${Math.floor(balance / 1000)}k` : fmt(balance);
    return (
      <a
        href={TOPUP_HREF}
        className={vx(
          "flex w-11 flex-col items-center gap-1 rounded-2xl border border-vs-ink/10 bg-vs-ink/[0.05] py-2 text-muted transition-colors hover:border-vs-accent/45 hover:bg-vs-ink/[0.09] hover:text-foreground",
          VS_FOCUS,
        )}
        title={`${amount} · ${topup}`}
        aria-label={`${amount}. ${topup}`}
      >
        <FiZap className="text-vs-accent" aria-hidden="true" />
        <span className="text-[11px] font-medium leading-none tabular-nums">{short}</span>
      </a>
    );
  }

  const rail = variant === "rail";
  return (
    <a
      href={TOPUP_HREF}
      className={vx(
        VS_PILL,
        "hover:!border-vs-accent/45",
        // Чип пониже, чтобы строка в 56 px не выглядела тесной; зону нажатия добирает CS_TALL_HIT.
        rail ? "!h-11 w-full justify-between md:!h-10" : vx(CS_TALL_HIT, "!h-9 md:!h-10"),
      )}
      title={topup}
      aria-label={rail ? undefined : `${amount}. ${topup}`}
    >
      <span className="inline-flex items-center gap-1.5">
        <FiZap className="shrink-0 text-vs-accent" aria-hidden="true" />
        <span className="font-semibold tabular-nums text-foreground">{amount}</span>
      </span>
      {rail && <span className="text-xs font-semibold text-vs-accent">{topup}</span>}
    </a>
  );
}

/* ------------------------------------------------------------------ */
/* Название мультфильма с переименованием                               */
/* ------------------------------------------------------------------ */

/**
 * Название открытого мультфильма; нажатие — переименовать. Мультфильма нет
 * (новый, ещё не заведённый) — на этом месте имя раздела.
 *
 * Родитель ставит key по id мультфильма: открыли другой — поле правки
 * закрывается вместе со старым названием.
 */
function MovieTitle({
  project,
  onRename,
  className = "",
}: {
  project: Project | null;
  onRename: (value: string) => void;
  className?: string;
}) {
  const { t } = useTranslation("common");
  const [editing, setEditing] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  // Enter закрывает поле, и следом может прийти blur — сохраняем один раз.
  const finished = useRef(false);

  useEffect(() => {
    if (!editing) return;
    finished.current = false;
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [editing]);

  if (!project) {
    return (
      <span className={vx("block min-w-0 truncate px-1.5 font-semibold text-foreground", className)}>
        {t("studio_ui.shell_name", { defaultValue: "Мультстудия" })}
      </span>
    );
  }

  const renameLabel = t("studio_ui.shell_rename", { defaultValue: "Переименовать" });

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        className={vx(
          "group inline-flex min-h-11 min-w-0 cursor-pointer items-center gap-1.5 rounded-xl px-1.5 text-left font-semibold text-foreground transition-colors hover:bg-vs-ink/[0.06] md:min-h-9",
          VS_FOCUS,
          className,
        )}
        title={renameLabel}
      >
        <span className="truncate">{project.title.trim() || t("studio_ui.movie_fallback", { id: project.id })}</span>
        {/* Карандаш на мыши — по наведению, на пальце (и в Telegram) — всегда: наведения там нет. */}
        <FiEdit2
          className="shrink-0 text-xs text-muted transition-opacity pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 pointer-fine:group-focus-visible:opacity-100"
          aria-hidden="true"
        />
      </button>
    );
  }

  const finish = (save: boolean) => {
    if (finished.current) return;
    finished.current = true;
    const next = (inputRef.current?.value || "").replace(/\s+/g, " ").trim().slice(0, MAX_TITLE_CHARS);
    setEditing(false);
    // Пустое название хук не сохраняет — у мультфильма остаётся прежнее.
    if (save && next && next !== project.title) onRename(next);
  };

  return (
    <input
      ref={inputRef}
      defaultValue={project.title}
      maxLength={MAX_TITLE_CHARS}
      onBlur={() => finish(true)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          finish(true);
        } else if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          finish(false);
        }
      }}
      placeholder={t("studio_ui.movie_title")}
      aria-label={renameLabel}
      // На телефоне шрифт поля не меньше 16 px: иначе iOS приближает страницу при фокусе.
      className={vx(
        "w-full min-w-0 rounded-xl border border-vs-ink/10 bg-vs-ink/[0.04] px-2.5 py-1.5 font-semibold text-foreground outline-none transition-colors placeholder:text-muted-2 focus:border-vs-accent/60 max-sm:!text-base",
        className,
      )}
    />
  );
}

/* ------------------------------------------------------------------ */
/* Строки верха                                                        */
/* ------------------------------------------------------------------ */

export type CartoonTopProps = {
  loading: boolean;
  authed: boolean;
  balance: number | null;
  balanceFailed?: boolean;
  /** Открытый мультфильм; null — новый, ещё не заведённый. */
  project: Project | null;
  /** Путь студии для возврата после входа (/studio или /tg/studio). */
  back: string;
  onRename: (value: string) => void;
};

/** Компьютер (≥1024): строка над лентой. Строка прозрачная — линию по прокрутке рисует оболочка. */
export function CartoonHeader({ loading, authed, balance, balanceFailed, project, back, onRename }: CartoonTopProps) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 px-4">
      <div className="min-w-0 flex-1">
        {/* Без мультфильма слева только имя раздела — тише, чем название мультфильма. */}
        <MovieTitle
          key={project?.id ?? "new"}
          project={project}
          onRename={onRename}
          className={project ? "max-w-full text-base" : "text-sm"}
        />
      </div>
      <BalancePill loading={loading} authed={authed} balance={balance} failed={balanceFailed} back={back} />
    </header>
  );
}

/** Телефон, планшет и Telegram (<1024): ☰, название, баланс. */
export default function CartoonTopBar({ onMenu, ...top }: CartoonTopProps & { onMenu: () => void }) {
  const { t } = useTranslation("common");
  return (
    <header className="flex h-[calc(3.5rem_+_env(safe-area-inset-top,0px))] shrink-0 items-center gap-1.5 px-2 pt-[env(safe-area-inset-top,0px)] sm:px-3">
      <button type="button" onClick={onMenu} className={VS_ICON_BTN} aria-label={t("studio_ui.my_movies")}>
        <FiMenu className="text-lg" aria-hidden="true" />
      </button>
      <div className="min-w-0 flex-1">
        <MovieTitle
          key={top.project?.id ?? "new"}
          project={top.project}
          onRename={top.onRename}
          className="max-w-full text-[15px]"
        />
      </div>
      <BalancePill
        loading={top.loading}
        authed={top.authed}
        balance={top.balance}
        failed={top.balanceFailed}
        back={top.back}
      />
    </header>
  );
}

/* ------------------------------------------------------------------ */
/* Ошибка над лентой                                                    */
/* ------------------------------------------------------------------ */

/**
 * Отказ сервера или сбой загрузки. Стоит над лентой, а не в ней: лента
 * прокручивается, и строка вверху страницы уезжала бы из виду вместе с ней.
 * По ширине — как секции ленты.
 */
export function ErrorBanner({ message, onClose }: { message: string; onClose: () => void }) {
  const { t } = useTranslation("common");
  const close = t("studio_ui.shell_close_error", { defaultValue: "Скрыть" });
  return (
    <div className={vx(VS_SECTION, "shrink-0 pt-1")}>
      <div role="alert" className={vx(CS_NOTE_FAIL, "flex items-start gap-3")}>
        <FiAlertCircle className="mt-0.5 shrink-0" aria-hidden="true" />
        <p className="min-w-0 flex-1 break-words">{message}</p>
        {/* Кружок 32 px, зона нажатия 44 px (before): выше ростом он раздул бы плашку. */}
        <button
          type="button"
          onClick={onClose}
          aria-label={close}
          title={close}
          className={vx(
            "relative -my-1 -mr-1.5 grid size-8 shrink-0 cursor-pointer place-items-center rounded-full transition-colors hover:bg-status-fail/15 before:absolute before:-inset-1.5",
            VS_FOCUS,
          )}
        >
          <FiX aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
