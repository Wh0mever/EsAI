"use client";

import { useEffect } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { IoClose } from "react-icons/io5";
import { FiGift } from "react-icons/fi";

type ExitDiscountPopupProps = {
  open: boolean;
  /** процент скидки — берём из ответа API, никогда не хардкодим в тексте */
  percent: number | null;
  /** сколько ещё действует предложение, в минутах — тоже из API (expires_at) */
  minutesLeft: number | null;
  claiming?: boolean;
  onClaim: () => void;
  onDecline: () => void;
};

/**
 * ExitDiscountPopup — модалка exit-intent скидки на /pricing.
 * Центр экрана, портал в document.body, затемнение фона, z-[1100] — тот же
 * уровень, что и остальные модалки проекта (Dialog.tsx), чтобы не конфликтовать
 * со стеком UI (сайдбары/чат).
 */
export default function ExitDiscountPopup({
  open,
  percent,
  minutesLeft,
  claiming = false,
  onClaim,
  onDecline,
}: ExitDiscountPopupProps) {
  const { t } = useTranslation("common");

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onDecline();
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow || "";
    };
  }, [open, onDecline]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/70 p-4"
      onClick={onDecline}
      role="dialog"
      aria-modal="true"
      aria-labelledby="exit-discount-title"
    >
      <div
        className="relative w-full max-w-md rounded-2xl border border-border bg-surface p-6 sm:p-8 shadow-lg text-center"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={onDecline}
          className="absolute right-4 top-4 text-xl text-muted hover:text-foreground transition-colors cursor-pointer"
          aria-label={t("exitDiscount.decline", { defaultValue: "Нет, спасибо" })}
        >
          <IoClose />
        </button>

        <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-accent-soft text-accent text-2xl">
          <FiGift />
        </div>

        <h2 id="exit-discount-title" className="text-xl sm:text-2xl font-semibold text-foreground">
          {t("exitDiscount.title", { defaultValue: "Не уходите без бонуса! 🎁" })}
        </h2>

        <p className="mt-3 text-muted">
          {t("exitDiscount.text", {
            defaultValue: "Специально для вас скидка {{percent}}% на любой пакет — успейте забрать её в течение {{minutes}} минут.",
            percent: percent ?? 0,
            minutes: minutesLeft ?? 0,
          })}
        </p>

        <div className="mt-6 flex flex-col gap-3">
          <button
            type="button"
            onClick={onClaim}
            disabled={claiming}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent text-on-accent font-semibold text-sm py-3 hover:bg-accent-strong transition-colors disabled:opacity-60 cursor-pointer"
          >
            {t("exitDiscount.claim", { defaultValue: "Забрать скидку" })}
          </button>
          <button
            type="button"
            onClick={onDecline}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-surface-3 text-foreground font-semibold text-sm py-3 hover:bg-surface-2 transition-colors cursor-pointer"
          >
            {t("exitDiscount.decline", { defaultValue: "Нет, спасибо" })}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
