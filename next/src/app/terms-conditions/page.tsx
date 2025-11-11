"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import Breadcrumb from "@/components/global/AnimatedCircleBg";

type TermSection = { id: string; title: string; paras: string[] };

export default function TermsPage() {
  const { t } = useTranslation("common");

  const title = t("terms.title");
  const sections = t("terms.sections", { returnObjects: true }) as TermSection[];

  return (
    <main className="mx-auto lg:pt-80 pt-50 overflow-hidden relative">
      <Breadcrumb />
      <div className="p-8 max-w-4xl mx-auto space-y-6 text-gray-200 text-sm">
        <h1 className="font-bold">{title}</h1>
        {sections?.map((s) => (
          <section key={s.id} className="flex flex-col gap-4">
            <h6>{s.title}</h6>
            {s.paras.map((p, i) => (
              <p key={i} className={(i > 0 ? "ps-10 " : "") + "text-sm leading-relaxed"}>{p}</p>
            ))}
          </section>
        ))}
      </div>
    </main>
  );
}
