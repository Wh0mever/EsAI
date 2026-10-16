"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiAlertCircle, FiArrowRight, FiEdit2, FiLogIn, FiMenu, FiX, FiZap } from "react-icons/fi";
import { rememberReturnPath } from "@/tools/authNext";
import { VS_FOCUS, VS_ICON_BTN, VS_PILL, VS_PILL_ON, VS_SECTION, vx } from "@/components/vstudio/ui/skin";
import { CS_NOTE_FAIL, CS_TALL_HIT } from "@/components/studio/ui/cartoonSkin";
import { MERGE_PATH, fillText } from "./mergeLogic";
import type { MergeBanner } from "./useMerge";

/**
 * Верх страницы склейки в оболочке студий (VStudioShell):
 *  - MergeHeader — компьютер (≥1024): название склейки с переименованием и баланс;
 *  - MergeTopBar — телефон и планшет: ☰ («Мои склейки» шторкой), название, баланс;
 *  - MergeBalance — баланс; нажатие — пополнение; у гостя — «Войти»;
 *  - MergeErrorBanner — отказ сервера над лентой.
 */

const MAX_TITLE_CHARS = 140;

const fmt = (n: number) => Math.max(0, Math.round(n)).toLocaleString("ru-RU");

export function signInHref(back = MERGE_PATH): string {
  return `/auth/signin?next=${encodeURIComponent(back)}`;
}

/* ------------------------------------------------------------------ */
/* Баланс                                                              */
/* ------------------------------------------------------------------ */

export type MergeBalanceProps = {
  variant?: "chip" | "rail" | "compact";
  loading: boolean;
  authed: boolean | null;
  balance: number | null;
  failed?: boolean;
  onTopup: () => void;
  /** Куда вернуть гостя после входа (адрес страницы вместе с ?add=). */
  back?: string;
};

export function MergeBalance({ variant = "chip", loading, authed, balance, failed = false, onTopup, back = MERGE_PATH }: MergeBalanceProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });

  if (loading) {
    // Заглушка той же величины: когда придут баланс или «Войти», соседи не сдвинутся.
    return (
      <span
        aria-hidden="true"
        className={vx(
          "shrink-0",
          variant === "compact"
            ? "h-12 w-11 rounded-2xl"
            : variant === "rail"
              ? "h-11 w-full rounded-full md:h-10"
              : "h-9 w-24 rounded-full md:h-10",
          "bg-vs-ink/[0.08] dark:bg-vs-ink/[0.06]",
        )}
      />
    );
  }

  if (!authed) {
    const signin = t("top.signin", { defaultValue: "Войти" });
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
  const amount = balance == null ? unknown : t("top.balance", { defaultValue: "{{n}} кр", n: fmt(balance) });
  const topup = t("top.topup", { defaultValue: "Пополнить" });

  if (variant === "compact") {
    const short = balance == null ? unknown : balance >= 10000 ? `${Math.floor(balance / 1000)}k` : fmt(balance);
    return (
      <button
        type="button"
        onClick={onTopup}
        className={vx(
          "flex w-11 cursor-pointer flex-col items-center gap-1 rounded-2xl border border-vs-ink/10 bg-vs-ink/[0.05] py-2 text-muted transition-colors hover:border-vs-accent/45 hover:bg-vs-ink/[0.09] hover:text-foreground",
          VS_FOCUS,
        )}
        title={`${amount} · ${topup}`}
        aria-label={`${amount}. ${topup}`}
      >
        <FiZap className="text-vs-accent" aria-hidden="true" />
        <span className="text-[11px] font-medium leading-none tabular-nums">{short}</span>
      </button>
    );
  }

  const rail = variant === "rail";
  return (
    <button
      type="button"
      onClick={onTopup}
      className={vx(
        VS_PILL,
        "hover:!border-vs-accent/45",
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
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* Название склейки                                                    */
/* ------------------------------------------------------------------ */

/**
 * Название открытой склейки; нажатие — переименовать (в любом состоянии,
 * даже пока она идёт). Новая, ещё не заведённая, — имя раздела.
 * Родитель ставит key по id склейки: открыли другую — поле правки закрывается.
 */
function MergeTitle({ title, named, onRename, className = "" }: { title: string; named: boolean; onRename: (v: string) => void; className?: string }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
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

  if (!named) {
    return (
      <span className={vx("block min-w-0 truncate px-1.5 font-semibold text-foreground", className)}>
        {t("merge.name", { defaultValue: "Склейка видео" })}
      </span>
    );
  }

  const renameLabel = t("nav.rename", { defaultValue: "Переименовать" });

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        className={vx(
          "group inline-flex min-h-11 min-w-0 max-w-full cursor-pointer items-center gap-1.5 rounded-xl px-1.5 text-left font-semibold text-foreground transition-colors hover:bg-vs-ink/[0.06] md:min-h-9",
          VS_FOCUS,
          className,
        )}
        title={renameLabel}
      >
        <span className="truncate">{title || t("merge.untitled", { defaultValue: "Без названия" })}</span>
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
    if (save && next && next !== title) onRename(next);
  };

  return (
    <input
      ref={inputRef}
      defaultValue={title}
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

export type MergeTopProps = {
  loading: boolean;
  authed: boolean | null;
  balance: number | null;
  balanceFailed: boolean;
  /** id открытой склейки (null — новая, ещё не заведённая). */
  openId: string | null;
  title: string;
  /** Куда вернуть гостя после входа. */
  back: string;
  onRename: (v: string) => void;
  onTopup: () => void;
};

export function MergeHeader({ loading, authed, balance, balanceFailed, openId, title, back, onRename, onTopup }: MergeTopProps) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 px-4">
      <div className="min-w-0 flex-1">
        <MergeTitle
          key={openId ?? "new"}
          title={title}
          named={Boolean(openId)}
          onRename={onRename}
          className={openId ? "text-base" : "text-sm"}
        />
      </div>
      <MergeBalance loading={loading} authed={authed} balance={balance} failed={balanceFailed} onTopup={onTopup} back={back} />
    </header>
  );
}

export default function MergeTopBar({ onMenu, ...top }: MergeTopProps & { onMenu: () => void }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  return (
    <header className="flex h-[calc(3.5rem_+_env(safe-area-inset-top,0px))] shrink-0 items-center gap-1.5 px-2 pt-[env(safe-area-inset-top,0px)] sm:px-3">
      <button type="button" onClick={onMenu} className={VS_ICON_BTN} aria-label={t("merge.rail.title", { defaultValue: "Мои склейки" })}>
        <FiMenu className="text-lg" aria-hidden="true" />
      </button>
      <div className="min-w-0 flex-1">
        <MergeTitle key={top.openId ?? "new"} title={top.title} named={Boolean(top.openId)} onRename={top.onRename} className="text-[15px]" />
      </div>
      <MergeBalance
        loading={top.loading}
        authed={top.authed}
        balance={top.balance}
        failed={top.balanceFailed}
        onTopup={top.onTopup}
        back={top.back}
      />
    </header>
  );
}

/* ------------------------------------------------------------------ */
/* Ошибка над лентой                                                    */
/* ------------------------------------------------------------------ */

export function MergeErrorBanner({ banner, onClose, onOpen }: { banner: MergeBanner; onClose: () => void; onOpen: (id: string) => void }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const close = t("merge.closeError", { defaultValue: "Скрыть" });
  const text = banner.text.key
    ? t(banner.text.key, { defaultValue: banner.text.ru, ...banner.text.params })
    : fillText(banner.text.ru, banner.text.params);
  const openId = banner.openId;
  return (
    <div className={vx(VS_SECTION, "shrink-0 pt-1")}>
      <div role="alert" className={vx(CS_NOTE_FAIL, "flex items-start gap-3")}>
        <FiAlertCircle className="mt-0.5 shrink-0" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="break-words">{text}</p>
          {openId && (
            <button
              type="button"
              onClick={() => onOpen(openId)}
              className={vx("mt-1 inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded-lg font-semibold underline-offset-4 hover:underline md:min-h-8", VS_FOCUS)}
            >
              {t("merge.openActive", { defaultValue: "Открыть идущую склейку" })}
              <FiArrowRight aria-hidden="true" />
            </button>
          )}
        </div>
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
