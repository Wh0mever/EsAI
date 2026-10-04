"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { FiCheck, FiCopy, FiShare2 } from "react-icons/fi";
import { Modal } from "@/components/dialog/Dialog";
import { useDialogFocus } from "@/components/creators/shared/useDialogFocus";
import ShareButtons from "@/components/ui/ShareButtons";
import { displayLink } from "@/lib/creators/format";
import { useCopy } from "./useCopy";

type Props = {
  code: string;
  /** Полная ссылка (https://…): на экране она без протокола, копируется целиком. */
  link: string;
  /** Промокод создан только что — один раз говорим, что ссылка появилась сама. */
  justCreated?: boolean;
};

/**
 * Главная кнопка креатора (ТЗ п.38): промокод, ссылка, «Скопировать» и
 * «Поделиться». Промокод и ссылка — один идентификатор; кнопки «изменить» нет:
 * код меняет только администратор.
 */
export default function CodeLink({ code, link, justCreated = false }: Props) {
  const { t } = useTranslation("creators", { useSuspense: false });
  const { copied, copy } = useCopy();
  const [shareOpen, setShareOpen] = useState(false);
  const shareRef = useDialogFocus<HTMLDivElement>(shareOpen);

  const copyLabel = t("dash.code.copy", { defaultValue: "Скопировать" });
  const copiedLabel = t("dash.code.copied", { defaultValue: "Скопировано" });
  const shareText = t("dash.code.share_text", {
    defaultValue: "Создавайте видео и мультфильмы с EsAI. Мой промокод: {{code}}",
    code,
  });

  const share = async () => {
    if (typeof navigator !== "undefined" && typeof navigator.share === "function") {
      try {
        await navigator.share({ text: shareText, url: link });
        return;
      } catch (e) {
        // Человек сам закрыл системное окно — это не ошибка, окно с кнопками не нужно.
        if (e instanceof Error && e.name === "AbortError") return;
      }
    }
    setShareOpen(true);
  };

  const rows = [
    { key: "code", label: t("dash.code.my_code", { defaultValue: "Мой промокод" }), shown: code, value: code },
    { key: "link", label: t("dash.code.my_link", { defaultValue: "Моя ссылка" }), shown: displayLink(link), value: link },
  ];

  return (
    <section className="rounded-2xl border border-border bg-surface px-2.5 py-1.5">
      {justCreated && (
        <p className="mb-1 text-[11.5px] font-medium leading-4 text-status-ok">
          {t("dash.code.created", { defaultValue: "Промокод сохранён. Персональная ссылка создана автоматически." })}
        </p>
      )}
      <div className="flex flex-col gap-0.5">
        {rows.map((row) => (
          <div key={row.key} className="flex items-center gap-2">
            <div className="min-w-0 flex-1">
              <div className="text-[10.5px] leading-[14px] text-muted">{row.label}</div>
              <div className="select-all break-all font-mono text-sm font-bold leading-5 text-foreground">{row.shown}</div>
            </div>
            <button
              type="button"
              onClick={() => void copy(row.key, row.value)}
              className="inline-flex h-8 shrink-0 cursor-pointer items-center gap-1 rounded-lg border border-border bg-surface-2 px-2.5 text-xs font-medium text-foreground transition-colors hover:border-accent"
            >
              {copied === row.key ? <FiCheck className="text-status-ok" aria-hidden /> : <FiCopy aria-hidden />}
              <span aria-live="polite">{copied === row.key ? copiedLabel : copyLabel}</span>
            </button>
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={() => void share()}
        className="mt-1.5 inline-flex h-8 w-full cursor-pointer items-center justify-center gap-1.5 rounded-lg bg-accent text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong"
      >
        <FiShare2 aria-hidden />
        {t("dash.code.share", { defaultValue: "Поделиться" })}
      </button>

      <Modal
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        title={t("dash.code.share", { defaultValue: "Поделиться" })}
        size="md"
      >
        <div ref={shareRef} tabIndex={-1} className="outline-none">
          <p className="mb-1 break-words text-sm text-muted">{shareText}</p>
          <p className="mb-4 break-all font-mono text-sm text-foreground">{displayLink(link)}</p>
          <ShareButtons
            url={link}
            text={shareText}
            labels={{
              copy: t("dash.code.share_copy", { defaultValue: "Скопировать ссылку" }),
              copied: copiedLabel,
              link: t("dash.code.share_link", { defaultValue: "Ссылка" }),
              more: t("dash.code.share_more", { defaultValue: "Ещё" }),
            }}
          />
        </div>
      </Modal>
    </section>
  );
}
