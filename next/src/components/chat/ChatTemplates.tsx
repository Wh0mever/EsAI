"use client";

import { useState, useEffect, useMemo } from "react";
import { LuLayoutTemplate } from "react-icons/lu";
import { Button } from "../ui/buttons/Buttons";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { Modal } from "@/components/dialog/Dialog";
import Tabs from "@/components/ui/tabs/Tabs";
import { TemplateCard } from "@/components/ui/cards/Cards";
import NoData from "@/components/global/NoData";
import { useLocalStorage } from "@/hooks/useLocalStorage";
import PurposeTabs from "@/components/sections/Category/PurposeTabs";
import TemplatesCreationForm from "@/components/forms/TemplateCreationForm";

type Template = {
  id: number;
  name: string;
  prompt: string;
  description: string;
  provider: string;
  usage_count: number;
  purpose: string;
};

type TemplatesPayload = {
  global?: Template[];
  personal?: Template[];
};

const ALL = "Все";

export default function AiTemplates() {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const [templates, setTemplates] = useState<TemplatesPayload>({});
  const [localTemplates, setLocalTemplates] = useLocalStorage<Record<string, Template>>("ai-templates", {});
  const [, setTemplateChanged] = useState(false);

  const toggleModal = () => setOpen((prev) => !prev);

  useEffect(() => {
    const loadTemplates = async () => {
      try {
        const res = await fetchData("ai/templates/", "GET", null, true);
        setTemplates(res?.data || {});
      } catch (error) {
        console.error("Ошибка загрузки шаблонов", error);
      }
    };
    loadTemplates();
  }, []);

  useEffect(() => {
    setTemplateChanged(true);
    const t = setTimeout(() => setTemplateChanged(false), 0);
    return () => clearTimeout(t);
  }, [localTemplates]);

  const globalPurposes = useMemo(
    () => Array.from(new Set((templates.global ?? []).map((x) => x.purpose))),
    [templates.global]
  );
  const personalPurposes = useMemo(
    () => Array.from(new Set((templates.personal ?? []).map((x) => x.purpose))),
    [templates.personal]
  );

  const [selectedGlobalPurpose, setSelectedGlobalPurpose] = useState<string>("");
  const [selectedPersonalPurpose, setSelectedPersonalPurpose] = useState<string>("");

  useEffect(() => {
    if (!selectedGlobalPurpose && globalPurposes.length) setSelectedGlobalPurpose(globalPurposes[0]);
  }, [globalPurposes, selectedGlobalPurpose]);

  useEffect(() => {
    if (!selectedPersonalPurpose && personalPurposes.length) setSelectedPersonalPurpose(personalPurposes[0]);
  }, [personalPurposes, selectedPersonalPurpose]);

  const filteredGlobal = useMemo(() => {
    const list = templates.global ?? [];
    if (selectedGlobalPurpose === ALL || !selectedGlobalPurpose) return list;
    return list.filter((t) => t.purpose === selectedGlobalPurpose);
  }, [templates.global, selectedGlobalPurpose]);

  const filteredPersonal = useMemo(() => {
    const list = templates.personal ?? [];
    if (selectedPersonalPurpose === ALL || !selectedPersonalPurpose) return list;
    return list.filter((t) => t.purpose === selectedPersonalPurpose);
  }, [templates.personal, selectedPersonalPurpose]);

  return (
    <>
      <Button
        className="text-gray-200 hover:bg-neutral-700/50 text-xl bg-neutral-900 duration-300 p-3 rounded-full"
        description={t("chat.templates.templates")}
        onClick={toggleModal}
      >
        <LuLayoutTemplate />
      </Button>

      <Modal title={t("chat.templates.templates")} onClose={() => setOpen(false)} size="full" open={open}>
        {/* ЕДИНЫЙ скролл внутри модалки */}
        <div className="h-full w-full flex flex-col overflow-hidden">
          {/* Контент (скролл именно тут) */}
          <div className="flex-1 w-full overflow-auto overscroll-contain touch-pan-y px-3 sm:px-6 py-3">
            {/* Двухпанельная сетка на >=lg */}
            <div className="flex w-full gap-3 sm:gap-4 lg:flex-row flex-col">
              {/* LEFT: табы и списки */}
              <div className="flex grow min-w-0">
                <div className="w-full">
                  <Tabs.Cards defaultValue="global" variant="solid" size="sm" keepAlive>
                    <Tabs.Card value="global" trigger={<div className="p-3">{t("chat.tabs.global")}</div>}>
                      <div className="px-1 sm:px-2">
                        <PurposeTabs
                          value={selectedGlobalPurpose || globalPurposes[0] || ""}
                          onChange={setSelectedGlobalPurpose}
                          purposes={globalPurposes}
                          showAll
                          allLabel={ALL}
                        />
                      </div>
                      <div className="mt-3 sm:mt-4 grid gap-2 sm:gap-3 pb-8 sm:pb-10 px-1 sm:px-2 [grid-template-columns:repeat(auto-fit,minmax(260px,1fr))]">
                        {filteredGlobal.map((template) => (
                          <TemplateCard
                            key={template.id ?? `${template.provider}-${template.name}`}
                            template={template}
                            localTemplates={localTemplates}
                            setLocalTemplates={setLocalTemplates}
                          />
                        ))}
                        {!templates?.global?.length && <NoData className="col-span-full" />}
                      </div>
                    </Tabs.Card>

                    <Tabs.Card value="personal" trigger={<div className="p-3">{t("chat.tabs.favorites")}</div>}>
                      <div className="px-1 sm:px-2">
                        <PurposeTabs
                          value={selectedPersonalPurpose || personalPurposes[0] || ""}
                          onChange={setSelectedPersonalPurpose}
                          purposes={personalPurposes}
                          showAll
                          allLabel={ALL}
                        />
                      </div>
                      <div className="mt-3 sm:mt-4 grid gap-2 sm:gap-3 pb-8 sm:pb-10 px-1 sm:px-2 [grid-template-columns:repeat(auto-fit,minmax(240px,1fr))]">
                        {filteredPersonal.map((template) => (
                          <TemplateCard
                            key={template.id ?? `${template.provider}-${template.name}`}
                            template={template}
                            changeUsed={() => setTemplateChanged(true)}
                            setLocalTemplates={setLocalTemplates}
                          />
                        ))}
                        {!templates?.personal?.length && <NoData className="col-span-full" />}
                      </div>
                    </Tabs.Card>

                    <Tabs.Card value="creation" trigger={<div className="p-3">{t("chat.tabs.create")}</div>}>
                      <div className="w-full flex justify-start items-start gap-3 sm:gap-5 px-1 sm:px-2">
                        <TemplatesCreationForm />
                      </div>
                    </Tabs.Card>
                  </Tabs.Cards>
                </div>
              </div>

              {/* RIGHT: активные шаблоны */}
              <div
                className={[
                  "w-full lg:w-[360px] lg:flex-none",
                  "min-w-0",
                  "flex flex-col gap-4 items-stretch",
                  "py-2 lg:py-4 px-1 sm:px-2 lg:px-2",
                ].join(" ")}
              >
                <h4 className="text-xl sm:text-2xl px-1">{t("chat.templates.activeTemplates")}</h4>

                {localTemplates && Object.keys(localTemplates).length > 0 ? (
                  <div className="w-full flex flex-col gap-3 sm:gap-4">
                    {Object.keys(localTemplates).map((key) => {
                      const template = localTemplates[key];
                      return (
                        <TemplateCard
                          key={template.id ?? `${template.provider}-${template.name}`}
                          template={template}
                          localTemplates={localTemplates}
                          setLocalTemplates={setLocalTemplates}
                        />
                      );
                    })}
                  </div>
                ) : (
                  <NoData className="max-w-[300px] self-center" />
                )}
              </div>
            </div>
          </div>
        </div>
      </Modal>
    </>
  );
}
