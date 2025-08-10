"use client";

import { useState, useEffect } from "react";
import { LuLayoutTemplate } from "react-icons/lu";
import { Button } from "../UI/Buttons/Buttons";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { Field, TextArea } from "../UI/Inputs/Inputs";
import { Modal } from "@/components/Dialog/Dialog";
import Tabs from "@/components/UI/Tabs/Tabs";
import { TemplateCard } from "@/components/UI/Cards/Cards";
import NoData from "@/components/NoData/NoData";

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
	const [activeTab, setActiveTab] = useState<"all" | "favorites" | "create">("all");
	const [templates, setTemplates] = useState<any>({});

	useEffect(() => {
		const loadTemplates = async () => {
			try {
				const res = await fetchData("ai/templates/", "GET", null, true);
				setTemplates(res?.data || []);
				console.log("Шаблоны загружены", res?.data);
			} catch (error) {
				console.error("Ошибка загрузки шаблонов", error);
			}
		};
		loadTemplates();
	}, []);

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
				<Tabs.Cards defaultValue="global" variant="solid" size="sm" keepAlive>
					<Tabs.Card value="global" trigger={<div className="p-3">{t("chat.tabs.global")}</div>}>
						<div className="mt-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 py-10">
							{templates?.global?.map((template: Template) => (
								<TemplateCard
									key={template.id ?? `${template.provider}-${template.name}`}
									title={template.name}
									description={template.description}
									provider={template.provider}
									usage_count={template.usage_count}
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
									title={template.name}
									description={template.description}
									provider={template.provider}
									usage_count={template.usage_count}
								/>
							))}
							{!templates?.personal?.length && <NoData />}
						</div>
					</Tabs.Card>
					<Tabs.Card value="creation" trigger={<div className="p-3">{t("chat.tabs.create")}</div>}>
						<div className="w-full flex justify-start items-center gap-5">
							<form action="" className="w-fit flex flex-col gap-5">
								<Field
									label={t("chat.templates.name")}
									name="name"
									placeholder={t("chat.templates.namePlaceholder")}
									required
									className="dark-field"
								/>
								<TextArea
									label={t("chat.templates.prompt")}
									name="prompt"
									placeholder={t("chat.templates.promptPlaceholder")}
									required
									rows={8}
									className="dark-field"
								/>
								<TextArea
									label={t("chat.templates.description")}
									name="prompt"
									placeholder={t("chat.templates.descriptionPlaceholder")}
									required
									rows={8}
									className="dark-field"
								/>

								<Button
									className="rounded-4xl bg-indigo-700 w-fit px-6 py-3 mt-5"
									onClick={toggleModal}
								>
									{t("chat.tabs.create")}
								</Button>
							</form>
						</div>
					</Tabs.Card>
				</Tabs.Cards>
			</Modal>
		</>
	);
}
