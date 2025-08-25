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
  const [templateChanged, setTemplateChanged] = useState(false);

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

  // purposes
  const globalPurposes = useMemo(
    () => Array.from(new Set((templates.global ?? []).map((x) => x.purpose))),
    [templates.global]
  );
  const personalPurposes = useMemo(
    () => Array.from(new Set((templates.personal ?? []).map((x) => x.purpose))),
    [templates.personal]
  );

  // selected purpose per tab
  const [selectedGlobalPurpose, setSelectedGlobalPurpose] = useState<string>("");
  const [selectedPersonalPurpose, setSelectedPersonalPurpose] = useState<string>("");

  useEffect(() => {
    if (!selectedGlobalPurpose && globalPurposes.length) setSelectedGlobalPurpose(globalPurposes[0]);
  }, [globalPurposes, selectedGlobalPurpose]);

  useEffect(() => {
    if (!selectedPersonalPurpose && personalPurposes.length) setSelectedPersonalPurpose(personalPurposes[0]);
  }, [personalPurposes, selectedPersonalPurpose]);

  // filtered lists
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

      <Modal
        title={t("chat.templates.templates")}
        onClose={() => setOpen(false)}
        size="full"
        open={open}
      >
        <div className="flex gap-4 h-full w-full lg:flex-row flex-col">
          <div className="flex grow">
            <Tabs.Cards defaultValue="global" variant="solid" size="sm" keepAlive>
              <Tabs.Card value="global" trigger={<div className="p-3">{t("chat.tabs.global")}</div>}>
                <PurposeTabs
                  value={selectedGlobalPurpose || globalPurposes[0] || ""}
                  onChange={setSelectedGlobalPurpose}
                  purposes={globalPurposes}
                  showAll
                  allLabel={ALL}
                />
                <div className="mt-4 grid grid-cols-1 md:grid-cols-1 lg:grid-cols-2 py-10 gap-3">
                  {filteredGlobal.map((template) => (
                    <TemplateCard
                      key={template.id ?? `${template.provider}-${template.name}`}
                      template={template}
                      localTemplates={localTemplates}
                      setLocalTemplates={setLocalTemplates}
                    />
                  ))}
                  {!templates?.global?.length && <NoData />}
                </div>
              </Tabs.Card>

              <Tabs.Card value="personal" trigger={<div className="p-3">{t("chat.tabs.favorites")}</div>}>
                <PurposeTabs
                  value={selectedPersonalPurpose || personalPurposes[0] || ""}
                  onChange={setSelectedPersonalPurpose}
                  purposes={personalPurposes}
                  showAll
                  allLabel={ALL}
                />
                <div className="mt-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 py-10 gap-3">
                  {filteredPersonal.map((template) => (
                    <TemplateCard
                      key={template.id ?? `${template.provider}-${template.name}`}
                      template={template}
                      changeUsed={() => setTemplateChanged} // как у тебя было
                    />
                  ))}
                  {!templates?.personal?.length && <NoData />}
                </div>
              </Tabs.Card>

              <Tabs.Card value="creation" trigger={<div className="p-3">{t("chat.tabs.create")}</div>}>
                <div className="w-full flex justify-start items-center gap-5">{/* your form here */}</div>
              </Tabs.Card>
            </Tabs.Cards>
          </div>

          <div className="w-fit min-w-[300px] flex flex-col gap-5 items-center py-10 px-2">
            <h4 className="text-2xl">{t("chat.templates.activeTemplates")}</h4>
            {localTemplates && Object.keys(localTemplates).length > 0 ? (
              <div className="w-full flex flex-col gap-4">
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
              <NoData className="max-w-[300px]" />
            )}
          </div>
        </div>
      </Modal>
    </>
  );
}
