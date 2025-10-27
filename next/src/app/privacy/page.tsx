"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import Breadcrumb from "@/components/global/AnimatedCircleBg";

type Section = { id: string; title: string; paras: string[] };

export default function PrivacyPolicyPage() {
  const { t } = useTranslation("privacy");
  const { t: tCommon } = useTranslation(); // defaultNS = common

  const title = t("title");
  const sections = t("sections", { returnObjects: true }) as Section[];

  const supportEmail = "support@esai.kg"
  const site = typeof window !== "undefined" ? window.location.origin : "";

  const withVars = (s: string) => s.replaceAll("{{email}}", supportEmail).replaceAll("{{site}}", site);

  return (
    <main className="mx-auto lg:pt-80 pt-50 overflow-hidden relative">
      <Breadcrumb />
      <div className="p-8 max-w-4xl mx-auto space-y-6 text-gray-200 text-lg">
        <h1 className="text-3xl font-bold">{title}</h1>
        {sections?.map((s) => (
          <section key={s.id} className="flex flex-col gap-4">
            <h6 className="text-xl">{s.title}</h6>
            {s.paras.map((p, i) => (
              <p key={i} className={i > 0 ? "ps-6" : ""}>{withVars(p)}</p>
            ))}
          </section>
        ))}
      </div>
    </main>
  );
}
