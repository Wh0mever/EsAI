"use client";

import "@/assets/style.scss";
import { IoIosArrowRoundForward } from "react-icons/io";
import ContactUsForm from "@/components/forms/ContactUs";
import { useTranslation } from "react-i18next";

export default function ContactUs() {
  const { t } = useTranslation("common");

  return (
    <main  className="w-full py-40 px-10">
      {/* контейнер страницы */}
      <section className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 pt-12 sm:pt-16 lg:pt-20">
        {/* две карточки: пишите / звоните */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-6 lg:gap-8">
          <div className="relative overflow-hidden rounded-2xl border border-gray-700 bg-neutral-900/40 p-6 sm:p-8 flex flex-col gap-4">
            <img src="/images/logo/head.svg" alt="" className="w-10 h-10" />
            <img
              src="/images/decorations/ai-template-card-bg.webp"
              alt=""
              className="pointer-events-none select-none absolute -top-8 -right-8 opacity-30 max-w-none"
            />
            <h5 className="text-lg sm:text-xl font-bold">{t("contact_us.write_title")}</h5>
            <p className="text-gray-300">{t("contact_us.write_description")}</p>

            <a
              href={`mailto:${t("contact_us.write_email")}`}
              className="mt-2 inline-flex items-center gap-1 border border-gray-700 py-3 px-5 rounded-lg bg-neutral-900 hover:bg-indigo-600 transition-all duration-300 w-full sm:w-auto"
            >
              <span>{t("contact_us.write_button")}</span>
              <i><IoIosArrowRoundForward /></i>
              <span className="truncate">{t("contact_us.write_email")}</span>
            </a>
          </div>

          <div className="relative overflow-hidden rounded-2xl border border-gray-700 bg-neutral-900/40 p-6 sm:p-8 flex flex-col gap-4">
            <img src="/images/logo/head.svg" alt="" className="w-10 h-10" />
            <img
              src="/images/decorations/ai-template-card-bg.webp"
              alt=""
              className="pointer-events-none select-none absolute -top-8 -right-8 opacity-30 max-w-none"
            />
            <h5 className="text-lg sm:text-xl font-bold">{t("contact_us.call_title")}</h5>
            <p className="text-gray-300">{t("contact_us.call_description")}</p>

            <a
              href={`tel:${t("contact_us.call_phone").replace(/[^+\d]/g, "")}`}
              className="mt-2 inline-flex items-center gap-1 border border-gray-700 py-3 px-5 rounded-lg bg-neutral-900 hover:bg-indigo-600 transition-all duration-300 w-full sm:w-auto"
            >
              <span>{t("contact_us.call_button")}</span>
              <i><IoIosArrowRoundForward /></i>
              <span className="truncate">{t("contact_us.call_phone")}</span>
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
