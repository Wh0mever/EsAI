"use client";

import { useTranslation } from "react-i18next";
import { FiLogIn, FiZap } from "react-icons/fi";
import { Modal } from "@/components/dialog/Dialog";
import { rememberReturnPath } from "@/tools/authNext";

/**
 * Всплывающие окна студии.
 *
 * Раньше и «не хватает кредитов», и «войдите, чтобы загрузить персонажа» были
 * строчками — одна вверху страницы, другая под формой. Клиент: «там не видно
 * вообще». В студии человек смотрит на сетку сцен посередине экрана, и текст
 * на краю он просто не замечает — а это два самых важных для нас момента:
 * оплата и регистрация. Поэтому оба разговора вынесены в окно.
 */

export function StudioPaywallDialog({
  open,
  required,
  balance,
  kind = "scene",
  onClose,
}: {
  open: boolean;
  required: number;
  balance: number;
  /** За что не хватило: у сцены и у своего героя разные цены и разный текст. */
  kind?: "scene" | "character";
  onClose: () => void;
}) {
  const { t } = useTranslation("common");
  const missing = Math.max(0, required - balance);

  return (
    <Modal open={open} onClose={onClose} title={t("studio_ui.paywall_title")} size="sm">
      <div className="flex flex-col gap-4">
        <p className="text-sm text-muted">
          {t(kind === "character" ? "studio_ui.short_note_character" : "studio_ui.short_note", {
            required,
            balance,
          })}
        </p>

        <div className="rounded-xl border border-accent/40 bg-accent/5 px-4 py-3 text-center">
          <div className="text-2xl font-bold text-foreground">
            {t("studio_ui.short_title", { count: missing })}
          </div>
        </div>

        <a
          href="/pricing/studio"
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-5 py-3 font-semibold text-on-accent transition-colors hover:bg-accent-strong"
        >
          <FiZap />
          {t("studio_ui.short_cta")}
        </a>
        <button
          type="button"
          onClick={onClose}
          className="text-sm text-muted transition-colors hover:text-foreground cursor-pointer"
        >
          {t("studio_ui.later")}
        </button>
      </div>
    </Modal>
  );
}

export function StudioAuthDialog({
  open,
  reason,
  onClose,
}: {
  open: boolean;
  /** Что человек пытался сделать — от этого зависит заголовок и пояснение. */
  reason: "character" | "scene" | "tryon" | "render";
  onClose: () => void;
}) {
  const { t } = useTranslation("common");
  const title = {
    character: "studio_ui.auth_character",
    scene: "studio_ui.auth_scene",
    tryon: "studio_ui.auth_tryon",
    render: "studio_ui.auth_render",
  }[reason];

  return (
    <Modal open={open} onClose={onClose} title={t(title)} size="sm">
      <div className="flex flex-col gap-4">
        {/* Гость уже собрал ленту — главное, что ему нужно знать: она не
            пропадёт, и после входа он окажется там же. */}
        <p className="text-sm text-muted">
          {t(reason === "character" ? "studio_ui.auth_note" : "studio_ui.auth_note_keep")}
        </p>
        <a
          href={`/auth/signin?next=${encodeURIComponent("/studio")}`}
          onClick={() => rememberReturnPath("/studio")}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-5 py-3 font-semibold text-on-accent transition-colors hover:bg-accent-strong"
        >
          <FiLogIn />
          {t("studio_ui.auth_cta")}
        </a>
        <button
          type="button"
          onClick={onClose}
          className="text-sm text-muted transition-colors hover:text-foreground cursor-pointer"
        >
          {t("studio_ui.later")}
        </button>
      </div>
    </Modal>
  );
}
