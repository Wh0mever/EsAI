"use client";

import "@/assets/style.scss";
import { IoIosArrowRoundForward } from "react-icons/io";
import ContactUsForm from "@/components/forms/ContactUs";
import { useTranslation } from "react-i18next";

export default function ContactUs() {
  const { t } = useTranslation("common");

  return (
    <main  className="w-full py-20 lg:py-40 lg:px-10">
      {/* контейнер страницы */}
      <section className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 pt-12 sm:pt-16 lg:pt-20">
        {/* две карточки: пишите / звоните */}
        <div className="grid grid-cols-1 gap-4 sm:gap-6 lg:gap-8 max-w-2xl mx-auto">
          <div className="relative overflow-hidden rounded-2xl border border-border bg-surface p-6 sm:p-8 flex flex-col gap-4">
            {/* Квадрат метки может сливаться с фоном карточки — лёгкая обводка */}
            <img src="/esai-mark.svg" alt="EsAI" className="w-10 h-10 rounded-xl ring-1 ring-border-strong" />
            <img
              src="/images/decorations/ai-template-card-bg.webp"
              alt=""
              className="pointer-events-none select-none absolute -top-8 -right-8 opacity-30 max-w-none"
            />
            <h5 className="text-lg sm:text-xl font-bold">{t("contact_us.write_title")}</h5>
            <p className="text-muted">{t("contact_us.write_description")}</p>

            <a
              href={`mailto:${t("contact_us.write_email")}`}
              className="mt-2 inline-flex items-center gap-1 border border-border py-3 px-5 rounded-lg bg-surface-2 hover:bg-accent hover:text-on-accent transition-all duration-300 w-full sm:w-auto"
            >
              <span>{t("contact_us.write_button")}</span>
              <i><IoIosArrowRoundForward /></i>
              <span className="truncate">{t("contact_us.write_email")}</span>
            </a>
          </div>
        </div>

        {/* форма + иллюстрация */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-10 items-start py-12 sm:py-16">
          <div className="order-2 lg:order-1">
            <ContactUsForm />
          </div>
          <div className="order-1 lg:order-2">
            <img
              src="/images/decorations/contact-us.svg"
              className="w-full h-auto max-h-[520px] object-contain"
              alt=""
            />
          </div>
        </div>
      </section>
    </main>
  );
}
