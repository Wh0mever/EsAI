"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/dialog/Dialog";

const FLAG = "esai-show-welcome";

/**
 * WelcomeModal — приветственное окно после регистрации (показывается ОДИН раз).
 * Триггер — localStorage-флаг "esai-show-welcome", который ставят:
 *  - email-вход (signin), если ответ confirm вернул is_new=true;
 *  - соц-вход (auth/callback), если в query пришёл welcome=1.
 * Флаг считывается и сразу удаляется, поэтому окно не появляется повторно.
 */
export default function WelcomeModal() {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    try {
      if (localStorage.getItem(FLAG) === "1") {
        localStorage.removeItem(FLAG);
        setOpen(true);
      }
    } catch {
      /* localStorage недоступен — просто не показываем */
    }
  }, []);

  if (!open) return null;

  return (
    <Modal
      title={t("welcome.title", { defaultValue: "🎉 Добро пожаловать в EsAI!" })}
      open={open}
      onClose={() => setOpen(false)}
      size="sm"
    >
      <div className="flex flex-col gap-5 p-1">
        <p className="text-muted leading-relaxed">
          {t("welcome.body", {
            defaultValue:
              "На ваш баланс уже начислены приветственные бонусные кредиты. Начните пользоваться EsAI прямо сейчас!",
          })}
        </p>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="inline-flex items-center justify-center rounded-xl bg-accent text-on-accent font-semibold text-sm py-3 hover:bg-accent-strong transition-colors cursor-pointer"
        >
          {t("welcome.cta", { defaultValue: "Начать" })}
        </button>
      </div>
    </Modal>
  );
}
