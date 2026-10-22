"use client";

import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { FiScissors } from "react-icons/fi";
import { Modal } from "@/components/dialog/Dialog";
import { VS_BTN_GHOST, VS_BTN_GOLD, VS_LABEL, vx } from "@/components/vstudio/ui/skin";
import type { SoundInfo } from "./audioLogic";
import { formatDuration } from "./mergeLogic";
import type { MergeAspect, MergeFit } from "./mergeTypes";
import { useSoundText } from "./soundText";

/**
 * Подтверждение перед склейкой: что склеится и сколько это стоит. Цена —
 * та же, что на кнопке; кредиты резервируются при запуске, а списываются,
 * только когда ролик сохранён. Звук сведётся вместе с роликом; голос и
 * музыка уже оплачены, и в цену склейки не входят.
 */
export default function MergeConfirmDialog({
  open,
  count,
  total,
  aspect,
  fit,
  price,
  retentionDays,
  sound,
  paid,
  voiceFrom = null,
  freeLimit = null,
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
  sound: SoundInfo;
  paid: "voice" | "music" | "both" | null;
  /** С какого ролика голос за кадром: номер с единицы и название; null — голоса нет. */
  voiceFrom?: { n: number; title: string } | null;
  /** Бесплатных склеек в сутки (только при цене 0); null — предела нет. */
  freeLimit?: number | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const soundText = useSoundText();
  const soundList = soundText.list(sound);
  const paidText = soundText.paid(paid);
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
          {soundList && (
            <>
              <dt className="text-muted">{t("merge.audio.title", { defaultValue: "Звук" })}</dt>
              <dd className="first-letter:uppercase text-foreground">{soundList}</dd>
            </>
          )}
          {voiceFrom && (
            <>
              <dt className="text-muted">{t("merge.confirm.voice", { defaultValue: "Голос" })}</dt>
              <dd className="min-w-0 break-words text-foreground">
                {t("merge.confirm.voiceFrom", {
                  defaultValue: "с №{{n}} — {{title}}",
                  n: voiceFrom.n,
                  title: voiceFrom.title,
                })}
              </dd>
            </>
          )}
        </dl>
        <div className="rounded-2xl border border-vs-accent/35 bg-accent/[0.08] px-4 py-3">
          <p className={VS_LABEL}>{t("merge.confirm.price", { defaultValue: "Цена" })}</p>
          <p className="mt-0.5 text-xl font-semibold tabular-nums text-foreground">{priceText}</p>
          <p className="mt-1 text-[13px] leading-snug text-muted">
            {price > 0
              ? t("merge.confirm.charge", {
                  defaultValue: "Спишутся, только когда ролик будет готов. Не получится — кредиты останутся у вас.",
                })
              : freeLimit
                ? t("merge.confirm.free_limit", {
                    defaultValue: "Склейка сейчас бесплатная — до {{max}} склеек в сутки.",
                    max: freeLimit,
                  })
                : t("merge.confirm.free", { defaultValue: "Склейка сейчас бесплатная." })}
          </p>
          {paidText && <p className="mt-1 text-[13px] leading-snug text-muted">{paidText}.</p>}
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
            {price > 0
              ? t("merge.dock.run", { defaultValue: "Склеить · {{price}}", price: priceText })
              : t("merge.dock.run_free", { defaultValue: "Склеить бесплатно" })}
          </button>
        </div>
      </div>
    </Modal>
  );
}
