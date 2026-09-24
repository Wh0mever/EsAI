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
 *
 * Окна общие для мультстудии (/studio) и видеостудии (/video-studio): куда
 * вернуть после входа (returnTo) и где пополнять (pricingHref) задаёт
 * вызывающий, как и свои тексты (title, note). Без этих пропсов поведение
 * прежнее — мультстудия ничего не передаёт.
 */

export function StudioPaywallDialog({
  open,
  required,
  balance,
  kind = "scene",
  onClose,
  pricingHref = "/pricing/studio",
  title,
  note,
  ctaLabel,
}: {
  open: boolean;
  required: number;
  balance: number;
  /** За что не хватило: у сцены и у своего героя разные цены и разный текст. */
  kind?: "scene" | "character" | "audio";
  onClose: () => void;
  /** Страница пополнения. По умолчанию — тарифы мультстудии. */
  pricingHref?: string;
  /** Свой заголовок окна (уже переведённый). */
  title?: string;
  /** Своё пояснение вместо текста про сцену/героя/звук (уже переведённое). */
  note?: string;
  /** Своя подпись кнопки пополнения. */
  ctaLabel?: string;
}) {
  const { t } = useTranslation("common");
  const missing = Math.max(0, required - balance);

  return (
    <Modal open={open} onClose={onClose} title={title || t("studio_ui.paywall_title")} size="sm">
      <div className="flex flex-col gap-4">
        <p className="text-sm text-muted">
          {note ||
            t(kind === "character" ? "studio_ui.short_note_character" : kind === "audio" ? "studio_ui.short_note_audio" : "studio_ui.short_note", {
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
          href={pricingHref}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-5 py-3 font-semibold text-on-accent transition-colors hover:bg-accent-strong"
        >
          <FiZap />
          {ctaLabel || t("studio_ui.short_cta")}
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
  reason = "render",
  onClose,
  returnTo = "/studio",
  title,
  note,
  onSignIn,
}: {
  open: boolean;
  /** Что человек пытался сделать — от этого зависит заголовок и пояснение. */
  reason?: "character" | "scene" | "tryon" | "render";
  onClose: () => void;
  /** Куда вернуть после входа (свой относительный путь). По умолчанию — мультстудия. */
  returnTo?: string;
  /** Свой заголовок (уже переведённый) вместо текста по reason. */
  title?: string;
  /** Своё пояснение (уже переведённое) вместо текста по reason. */
  note?: string;
  /** Перед уходом на вход: например, дописать черновик в браузер. */
  onSignIn?: () => void;
}) {
  const { t } = useTranslation("common");
  const titleKey = {
    character: "studio_ui.auth_character",
    scene: "studio_ui.auth_scene",
    tryon: "studio_ui.auth_tryon",
    render: "studio_ui.auth_render",
  }[reason];

  return (
    <Modal open={open} onClose={onClose} title={title || t(titleKey)} size="sm">
      <div className="flex flex-col gap-4">
        {/* Гость уже собрал ленту — главное, что ему нужно знать: она не
            пропадёт, и после входа он окажется там же. */}
        <p className="text-sm text-muted">
          {note || t(reason === "character" ? "studio_ui.auth_note" : "studio_ui.auth_note_keep")}
        </p>
        <a
          href={`/auth/signin?next=${encodeURIComponent(returnTo)}`}
          onClick={() => {
            onSignIn?.();
            rememberReturnPath(returnTo);
          }}
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
