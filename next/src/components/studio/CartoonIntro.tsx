"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";
import { FiArrowRight } from "react-icons/fi";
import { VS_BTN_LINK, VS_SECTION, VS_SUB, vx } from "@/components/vstudio/ui/skin";
import { VSTUDIO_NAV } from "./cartoonTypes";

/**
 * Заголовок мультстудии: единственный h1 страницы и короткое пояснение.
 * Компактный — это рабочий экран, а не витрина: сразу под ним герои и сцены.
 */
export default function CartoonIntro({ host = "site" }: { host?: "site" | "tg" }) {
  const { t } = useTranslation("common");
  return (
    <header className={vx(VS_SECTION, "pt-5 sm:pt-8")}>
      <h1 className="vs-display text-[26px] leading-tight text-foreground sm:text-[32px]">{t("studio_ui.title")}</h1>
      <p className={vx(VS_SUB, "mt-1.5 max-w-2xl")}>{t("studio_ui.subtitle")}</p>
      {/* Студия собирает ролик из готовых сцен. Кому нужен свой сюжет по
          описанию — тому в видеостудию, а отсюда о ней было не узнать. Из
          Telegram не уводим: видеостудии в Mini App нет. */}
      {VSTUDIO_NAV && host === "site" && (
        <Link
          href="/video-studio"
          prefetch={false}
          // На телефоне строка переносится в две — кольцо фокуса скруглённым прямоугольником, а не пилюлей.
          className={vx(
            VS_BTN_LINK,
            "-ml-2 mt-1 flex-wrap gap-y-0 !rounded-xl py-1 text-left !text-vs-accent [&:hover>span:last-child]:underline",
          )}
        >
          <span className="text-muted">
            {t("studio_ui.vstudio_hint", { defaultValue: "Нужно видео не из готовых сцен?" })}
          </span>
          <span className="inline-flex items-center gap-1.5 font-semibold underline-offset-4">
            {t("studio_ui.vstudio_link", { defaultValue: "Откройте видеостудию" })}
            <FiArrowRight aria-hidden="true" />
          </span>
        </Link>
      )}
    </header>
  );
}
