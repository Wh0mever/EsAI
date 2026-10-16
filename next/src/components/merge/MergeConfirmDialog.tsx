"use client";

import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { FiScissors } from "react-icons/fi";
import { Modal } from "@/components/dialog/Dialog";
import { VS_BTN_GHOST, VS_BTN_GOLD, VS_LABEL, vx } from "@/components/vstudio/ui/skin";
import { formatDuration } from "./mergeLogic";
import type { MergeAspect, MergeFit } from "./mergeTypes";

/**
 * Подтверждение перед склейкой: что склеится и сколько это стоит. Цена —
 * та же, что на кнопке; кредиты резервируются при запуске, а списываются,
 * только когда ролик сохранён.
 */
export default function MergeConfirmDialog({
  open,
  count,
  total,
  aspect,
  fit,
  price,
  retentionDays,
  onConfirm,
  onClose,
}: {
  open: boolean;
  count: number;
  total: number;
  aspect: MergeAspect;
  fit: MergeFit;
  price: number;
  retentionDays: number;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const confirmRef = useRef<HTMLButtonElement>(null);
  // Окно открылось — фокус на «Склеить»: Enter подтверждает, Esc закрывает.
  useEffect(() => {
    if (open) confirmRef.current?.focus();
  }, [open]);
  const priceText = price > 0 ? t("top.balance", { defaultValue: "{{n}} кр", n: price }) : t("merge.dock.free", { defaultValue: "бесплатно" });
  const fitText = fit === "crop" ? t("merge.fit.crop", { defaultValue: "Обрезать" }) : t("merge.fit.pad", { defaultValue: "Поля" });

  return (
    <Modal open={open} onClose={onClose} title={t("merge.confirm.title", { defaultValue: "Склеить видео?" })} size="sm">
      <div className="flex flex-col gap-4 text-foreground">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          <dt className="text-muted">{t("merge.confirm.what", { defaultValue: "Фрагментов" })}</dt>
          <dd className="tabular-nums text-foreground">
            {count} · {formatDuration(total)}
          </dd>
          <dt className="text-muted">{t("merge.dock.format", { defaultValue: "Формат" })}</dt>
          <dd className="text-foreground">
            {aspect} · {fitText}
          </dd>
        </dl>
        <div className="rounded-2xl border border-vs-accent/35 bg-accent/[0.08] px-4 py-3">
          <p className={VS_LABEL}>{t("merge.confirm.price", { defaultValue: "Цена" })}</p>
          <p className="mt-0.5 text-xl font-semibold tabular-nums text-foreground">{priceText}</p>
          <p className="mt-1 text-[13px] leading-snug text-muted">
            {price > 0
              ? t("merge.confirm.charge", {
                  defaultValue: "Спишутся, только когда ролик будет готов. Не получится — кредиты останутся у вас.",
                })
              : t("merge.confirm.free", { defaultValue: "Склейка сейчас бесплатная." })}
          </p>
        </div>
        <p className="text-[13px] leading-snug text-muted">
          {t("merge.confirm.keep", {
            defaultValue: "Готовый ролик хранится {{days}} дн. — скачайте его, чтобы не потерять.",
            days: retentionDays,
          })}
        </p>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} className={vx(VS_BTN_GHOST, "w-full sm:w-auto")}>
            {t("nav.cancel", { defaultValue: "Отмена" })}
          </button>
          <button ref={confirmRef} type="button" onClick={onConfirm} className={vx(VS_BTN_GOLD, "w-full sm:w-auto")}>
            <FiScissors aria-hidden="true" />
            {t("merge.dock.run", { defaultValue: "Склеить · {{price}}", price: priceText })}
          </button>
        </div>
      </div>
    </Modal>
  );
}
