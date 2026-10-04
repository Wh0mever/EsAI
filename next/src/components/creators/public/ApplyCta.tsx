"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";
import { FiArrowRight, FiCheckCircle, FiClock, FiSlash, FiXCircle } from "react-icons/fi";
import { errorText } from "@/lib/creators/errors";
import { fmtDate } from "@/lib/creators/format";
import { statusLabel } from "@/lib/creators/labels";
import type { Application } from "@/lib/creators/types";
import type { Stage } from "./applyLogic";
import { BTN_PRIMARY, BTN_SECONDARY, DASHBOARD_URL, SIGNIN_TO_APPLY } from "./ui";

type Props = {
  stage: Stage;
  /** Последняя заявка человека: дата отправки и причина отказа. Может не загрузиться — тогда null. */
  application: Application | null;
  /** Открыть форму заявки. */
  onApply: () => void;
  className?: string;
};

/**
 * Главное действие страницы — одно и то же в шапке и внизу. Что именно стоит
 * на этом месте, зависит от человека: гостю — вход, вошедшему — форма, а тому,
 * кто уже подал заявку или участвует, — карточка статуса вместо кнопки.
 */
export default function ApplyCta({ stage, application, onApply, className = "" }: Props) {
  const { t, i18n } = useTranslation("creators", { useSuspense: false });

  if (stage === "guest") {
    return (
      <Link href={SIGNIN_TO_APPLY} className={`${BTN_PRIMARY} ${className}`}>
        {t("public.cta.join", { defaultValue: "СТАТЬ ESAI CREATOR" })}
        <FiArrowRight aria-hidden className="shrink-0 text-base" />
      </Link>
    );
  }

  if (stage === "can_apply") {
    return (
      <button type="button" onClick={onApply} className={`${BTN_PRIMARY} ${className}`}>
        {t("public.cta.join", { defaultValue: "СТАТЬ ESAI CREATOR" })}
        <FiArrowRight aria-hidden className="shrink-0 text-base" />
      </button>
    );
  }

  const card = `w-full max-w-md rounded-2xl border bg-surface p-4 text-left sm:p-5 ${className}`;
  const head = "flex items-start gap-3";
  const title = "break-words text-base font-semibold text-foreground";
  const note = "mt-1 break-words text-sm text-muted";

  if (stage === "pending") {
    const sent = application?.status === "new" ? fmtDate(application.created_at, i18n.language) : "";
    return (
      <div className={`${card} border-status-wait/40`}>
        <div className={head}>
          <FiClock aria-hidden className="mt-0.5 shrink-0 text-xl text-status-wait" />
          <div className="min-w-0">
            <div className={title}>{statusLabel(t, "application", "new")}</div>
            {sent && (
              <div className={note}>{t("apply.status.sent", { defaultValue: "Отправлена {{date}}", date: sent })}</div>
            )}
            <p className={note}>
              {t("apply.status.pending_text", {
                defaultValue: "Мы проверяем каждую заявку вручную и сообщим о решении.",
              })}
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (stage === "rejected") {
    const reason = application?.status === "rejected" ? (application.reject_reason || "").trim() : "";
    return (
      <div className={`${card} border-status-fail/40`}>
        <div className={head}>
          <FiXCircle aria-hidden className="mt-0.5 shrink-0 text-xl text-status-fail" />
          <div className="min-w-0 flex-1">
            <div className={title}>{statusLabel(t, "application", "rejected")}</div>
            {reason && (
              // Причину пишет администратор — показываем как есть, с переносами строк.
              <p className="mt-2 whitespace-pre-line break-words rounded-xl bg-surface-2 px-3 py-2 text-sm text-foreground">
                <span className="text-muted">{t("apply.status.reason", { defaultValue: "Причина:" })}</span> {reason}
              </p>
            )}
            <button type="button" onClick={onApply} className={`${BTN_SECONDARY} mt-3 w-full sm:w-auto`}>
              {t("apply.status.again", { defaultValue: "Подать заявку снова" })}
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (stage === "apply_blocked") {
    return (
      <div className={`${card} border-status-fail/40`}>
        <div className={head}>
          <FiSlash aria-hidden className="mt-0.5 shrink-0 text-xl text-status-fail" />
          <div className={`min-w-0 ${title}`}>{errorText(t, { code: "apply_blocked" })}</div>
        </div>
      </div>
    );
  }

  // Креатор: активный или заблокированный — кабинет открыт обоим (второму только на чтение).
  const blocked = stage === "creator_blocked";
  return (
    <div className={`${card} ${blocked ? "border-status-fail/40" : "border-status-ok/40"}`}>
      <div className={head}>
        <FiCheckCircle aria-hidden className="mt-0.5 shrink-0 text-xl text-status-ok" />
        <div className="min-w-0 flex-1">
          <div className={title}>{t("apply.status.member", { defaultValue: "Вы участник программы" })}</div>
          {blocked && <p className="mt-1 break-words text-sm text-status-fail">{errorText(t, { code: "creator_blocked" })}</p>}
          <Link href={DASHBOARD_URL} className={`${BTN_PRIMARY} mt-3 w-full sm:w-auto`}>
            {t("public.cta.cabinet", { defaultValue: "Открыть кабинет" })}
            <FiArrowRight aria-hidden className="shrink-0 text-base" />
          </Link>
        </div>
      </div>
    </div>
  );
}
