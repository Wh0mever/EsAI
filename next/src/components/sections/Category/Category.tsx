"use client";

import React, { useEffect, useMemo, useState } from "react";
import { BsStars } from "react-icons/bs";
import { Button } from "@/components/ui/buttons/Buttons";
import { CiHeart } from "react-icons/ci";
import { TextTag } from "@/components/ui/text/Text";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import PurposeTabs from "@/components/sections/Category/PurposeTabs";

type Template = {
  id: number;
  name: string;
  description: string;
  template: string;
  usage_count: number;
  purpose: string;
};

const ALL = "All";

export default function Category() {
  const { t } = useTranslation("home");
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedPurpose, setSelectedPurpose] = useState<string>("");

  useEffect(() => {
    const loadTemplates = async () => {
      try {
        const res = await fetchData("ai/templates/", "GET", null, true);
        const list: Template[] = res?.ok && res?.data?.global ? res.data.global : [];
        setTemplates(list);
        if (list.length > 0) setSelectedPurpose(ALL);
      } catch (e) {
        console.error("Ошибка загрузки шаблонов", e);
      } finally {
        setLoading(false);
      }
    };
    loadTemplates();
  }, []);

  const purposes = useMemo(
    () => Array.from(new Set(templates.map((tpl) => tpl.purpose))),
    [templates]
  );

  const visible = useMemo(() => {
    if (selectedPurpose === ALL) return templates;
    return templates.filter((tpl) => tpl.purpose === selectedPurpose);
  }, [templates, selectedPurpose]);

  return (
    <section className="px-10 py-20 lg:px-30 lg:py-30 section-divider flex flex-col gap-5">
      <img
        src="/images/decorations/ai-tools-shape-left.webp"
        alt=""
        className="absolute left-0 top-0 -z-10"
      />
      <div className="mt-2 flex flex-col items-center justify-center gap-5 text-center">
        <TextTag text={t("aiTemplates.subtitle")} />
        <h2 className="text-4xl font-semibold">{t("aiTemplates.title")}</h2>
      </div>

      <PurposeTabs
        value={selectedPurpose || purposes[0] || ""}
        onChange={setSelectedPurpose}
        purposes={purposes}
        showAll
        allLabel={ALL}
      />

      {loading ? (
        <p className="text-center text-gray-400">Loading...</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-1 md:grid-cols-2 gap-5">
          {visible.map((tpl) => (
            <div
              key={tpl.id}
              className="flex flex-col gap-3 p-10 card-hover-colored bg-gray-800/5 border border-gray-700 rounded-xl hover:shadow-lg hover:bg-gray-800/10 hover:border-gray-600 colored-center"
              style={{ animation: "showCard 0.5s ease-in-out forwards" }}
            >
              <img
                src="/images/decorations/ai-template-card-bg.webp"
                alt=""
                className="absolute h-full w-full left-0 top-0 -z-10"
              />
              <i className="text-3xl p-5 flex rounded-full w-fit h-fit bg-indigo-800/25 text-white">
                <BsStars />
              </i>
              <div>
                <h3 className="text-white font-semibold text-lg">{tpl.name}</h3>
                {tpl.description && (
                  <p className="text-gray-400 text-sm mt-1">{tpl.description}</p>
                )}
              </div>
              <div className="text-gray-500 flex items-center justify-between mt-3">
                <p className="text-sm ">{tpl.usage_count} generated</p>
                <Button className="text-2xl cursor-pointer flex items-center justify-center p-2 rounded-full hover:text-indigo-600 hover:bg-white/75 transition-colors">
                  <CiHeart className="inline-block mr-1" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
