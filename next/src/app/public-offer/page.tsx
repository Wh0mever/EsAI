"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import Breadcrumb from "@/components/global/AnimatedCircleBg";

type Section = { id: string; title: string; paras: string[] };

export default function PublicOfferPage() {
  const { t, i18n } = useTranslation("offer");
  const { t: tCommon } = useTranslation(); // defaultNS = common

  const title = t("title");
  const sections = t("sections", { returnObjects: true }) as Section[];
  const appendixTitle = t("appendix.title");
  const appendixParas = t("appendix.paras", { returnObjects: true }) as string[];

  // Fill dynamic placeholders (site and email) client-side
  const site = typeof window !== "undefined" ? window.location.origin : "";
  const supportEmail = (process.env.NEXT_PUBLIC_SUPPORT_EMAIL as string) || tCommon("write_email");

  function withVars(text: string) {
    return text
      .replaceAll("{{site}}", site)
      .replaceAll("{{email}}", supportEmail);
  }

  return (
    <main className="mx-auto lg:pt-80 pt-50 overflow-hidden relative">
      <Breadcrumb />
      <div className="p-8 max-w-4xl mx-auto space-y-6 text-gray-200 text-sm">
        <h1 className="font-bold">{title}</h1>
        {sections?.map((s) => (
          <section key={s.id} className="flex flex-col gap-4">
            <h6>{s.title}</h6>
            {s.paras.map((p, i) => (
              <p key={i} className={(i > 0 ? "ps-6 " : "") + "text-sm leading-relaxed"}>{withVars(p)}</p>
            ))}
          </section>
        ))}

        <section className="flex flex-col gap-4">
          <h6>{appendixTitle}</h6>
          {appendixParas.map((p, i) => (
            <p key={i} className={(i > 0 ? "ps-6 " : "") + "text-sm leading-relaxed"}>{withVars(p)}</p>
          ))}
        </section>
      </div>
    </main>
  );
}
