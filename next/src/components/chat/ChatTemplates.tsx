"use client";

import { useState, useEffect } from "react";
import { LuLayoutTemplate } from "react-icons/lu";
import { Button } from "../ui/buttons/Buttons";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { Field, TextArea } from "../ui/inputs/Inputs";
import { Modal } from "@/components/dialog/Dialog";
import Tabs from "@/components/ui/tabs/Tabs";
import { TemplateCard } from "@/components/ui/cards/Cards";
import NoData from "@/components/global/NoData";
import { useLocalStorage } from "@/hooks/useLocalStorage";

type Template = {
	id: number;
	name: string;
	prompt: string;
	description: string;
	provider: string;
	usage_count: number;
};

export default function AiTemplates() {
	const { t } = useTranslation("common");
	const [open, setOpen] = useState(false);
	const [templates, setTemplates] = useState<any>({});
	const [localTemplates, setLocalTemplates] = useLocalStorage<any>("ai-templates", {});
	const [templateChanged, setTemplateChanged] = useState(false);

	useEffect(() => {
		const loadTemplates = async () => {
			try {
				const res = await fetchData("ai/templates/", "GET", null, true);
				setTemplates(res?.data || []);
			} catch (error) {
				console.error("Ошибка загрузки шаблонов", error);
			}
		};
		loadTemplates();
	}, []);

	useEffect(() => {
		setTemplateChanged(true);

		setTimeout(() => {
			setTemplateChanged(false);
		});
	}, [localTemplates, setTemplateChanged]);



	const toggleModal = () => setOpen((prev) => !prev);

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
				onClose={() => {
					setOpen(false);
				}}
				size="full"
				open={open}
			>
				<div className="flex gap-4 h-full w-full lg:flex-row flex-col">
					<div className="flex grow">
						<Tabs.Cards defaultValue="global" variant="solid" size="sm" keepAlive>
							<Tabs.Card value="global" trigger={<div className="p-3">{t("chat.tabs.global")}</div>}>
								<div className="mt-4 grid grid-cols-1 md:grid-cols-1 lg:grid-cols-2 py-10">
									{templates?.global?.map((template: Template) => (
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
								<div className="mt-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 py-10">
									{templates?.personal?.map((template: Template) => (
										<TemplateCard
											key={template.id ?? `${template.provider}-${template.name}`}
											template={template}
											changeUsed={() => setTemplateChanged}
										/>
									))}
									{!templates?.personal?.length && <NoData />}
								</div>
							</Tabs.Card>
							<Tabs.Card value="creation" trigger={<div className="p-3">{t("chat.tabs.create")}</div>}>
								<div className="w-full flex justify-start items-center gap-5">

								</div>
							</Tabs.Card>
						</Tabs.Cards>
					</div>

					<div className="w-fit min-w-[300px] flex flex-col gap-5 items-center py-10 px-2">
						<h4 className="text-2xl">{t("chat.templates.activeTemplates")}</h4>

						{localTemplates && Object.keys(localTemplates).length > 0 ? (
							<div className="w-full flex flex-col gap-3">
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
