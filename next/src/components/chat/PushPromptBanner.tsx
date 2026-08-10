"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiBell, FiX } from "react-icons/fi";
import { pushSupported, pushPermission, enablePush } from "@/tools/webPush";
import { useBonusSettings } from "@/hooks/useBonusSettings";

const DISMISS_KEY = "esai-push-prompt-dismissed";

type Props = {
  /** Показывать только авторизованным: подписка сохраняется за пользователем. */
  authed: boolean;
  /** Пользователь уже получил первый ответ ИИ. */
  ready: boolean;
};

/**
 * PushPromptBanner — предложение включить уведомления о ежедневных бесплатных
 * кредитах. Показывается ОДИН раз, сразу после первого ответа ИИ.
 *
 * Почему именно здесь: на подписку было оформлено 3 человека из 366, потому
 * что включить её можно было только через переключатель в боковом меню чата —
 * туда никто не доходил. При этом ежедневное начисление кредитов и есть
 * главный механизм возврата пользователей.
 *
 * Почему после первого ответа, а не при входе: браузер даёт ровно одну
 * попытку. Если спросить до того, как человек увидел пользу, он жмёт
 * «Запретить» — и канал закрыт навсегда, повторно спросить нельзя. После
 * первого удачного ответа мотивация максимальная.
 *
 * Сам баннер разрешение НЕ запрашивает — только по клику на кнопку
 * (обязательное требование iOS: requestPermission должен быть вызван из
 * пользовательского жеста, см. tools/webPush.ts).
 */
export default function PushPromptBanner({ authed, ready }: Props) {
  const { t } = useTranslation("common");
  const bonus = useBonusSettings();
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!authed || !ready) return;
    if (!pushSupported()) return;
    // 'granted' — уже подписан, 'denied' — браузер больше не спросит: в обоих
    // случаях баннер бессмыслен.
    if (pushPermission() !== "default") return;
    try {
      if (localStorage.getItem(DISMISS_KEY) === "1") return;
    } catch {}
    setVisible(true);
  }, [authed, ready]);

  const dismiss = () => {
    setVisible(false);
    try {
      localStorage.setItem(DISMISS_KEY, "1");
    } catch {}
  };

  const enable = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const res = await enablePush();
      if (res === "granted") {
        setDone(true);
        // Больше не предлагаем — подписка оформлена.
        try {
          localStorage.setItem(DISMISS_KEY, "1");
        } catch {}
        setTimeout(() => setVisible(false), 2200);
      } else {
        // Отказ/ошибка: не мозолим глаза, второй раз браузер всё равно не спросит.
        dismiss();
      }
    } finally {
      setBusy(false);
    }
  };

  if (!visible) return null;

  return (
    <div className="mx-auto w-full max-w-3xl px-1 pb-2">
      <div className="relative flex items-start gap-3 rounded-2xl border border-accent/40 bg-accent-soft px-4 py-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-surface text-accent-strong">
          <FiBell />
        </span>

        <div className="min-w-0 flex-1">
          {done ? (
            <p className="text-sm font-semibold text-foreground">
              {t("push.prompt_done", {
                defaultValue: "Готово! Сообщим, когда кредиты пополнятся.",
              })}
            </p>
          ) : (
            <>
              <p className="text-sm font-semibold text-foreground leading-snug">
                {t("push.prompt_title", {
                  count: bonus.daily_free_credits,
                  defaultValue:
                    "Напоминать, когда придут бесплатные кредиты? Каждый день до {{count}}.",
                })}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={enable}
                  disabled={busy}
                  className="rounded-full bg-accent px-4 py-1.5 text-xs sm:text-sm font-semibold text-on-accent hover:bg-accent-strong transition-colors cursor-pointer disabled:opacity-60"
                >
                  {busy
                    ? t("common.processing", { defaultValue: "Обработка..." })
                    : t("push.prompt_enable", { defaultValue: "Напоминать" })}
                </button>
                <button
                  type="button"
                  onClick={dismiss}
                  className="rounded-full px-3 py-1.5 text-xs sm:text-sm font-medium text-muted hover:text-foreground transition-colors cursor-pointer"
                >
                  {t("push.prompt_later", { defaultValue: "Не нужно" })}
                </button>
              </div>
            </>
          )}
        </div>

        <button
          type="button"
          onClick={dismiss}
          aria-label={t("common.close", { defaultValue: "Закрыть" })}
          className="shrink-0 -mr-1 -mt-1 p-1.5 rounded-lg text-muted hover:text-foreground hover:bg-surface transition-colors cursor-pointer"
        >
          <FiX />
        </button>
      </div>
    </div>
  );
}
