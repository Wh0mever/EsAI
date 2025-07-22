"use client";

import { useState, useEffect } from "react";
import { LuLayoutTemplate } from "react-icons/lu";
import { Button } from "../UI/Buttons/Buttons";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { Field, TextArea } from "../UI/Inputs/Inputs";
import { Modal } from "@/components/Dialog/Dialog";

type Template = {
	id: number;
	name: string;
	prompt: string;
	is_favorite: boolean;
};

export default function AiTemplates() {
	const { t } = useTranslation("common");
	const [open, setOpen] = useState(false);
	const [activeTab, setActiveTab] = useState<"all" | "favorites" | "create">("all");
	const [templates, setTemplates] = useState<Template[]>([]);

	useEffect(() => {
		const loadTemplates = async () => {
			try {
				const res = await fetchData("ai/templates/", "GET", null, true);
				setTemplates(res?.data || []);
				console.log(res?.data);
			} catch (error) {
				console.error("Ошибка загрузки шаблонов", error);
			}
		};
		loadTemplates();
	}, []);

	const toggleModal = () => setOpen((prev) => !prev);

	const handleTab = (tab: typeof activeTab) => setActiveTab(tab);

	return (
		<>
			<Button
				className="text-gray-200 hover:bg-neutral-700/50 text-xl bg-neutral-900 duration-300 p-3 rounded-full"
				description={t("chat.templates")}
				onClick={toggleModal}
			>
				<LuLayoutTemplate />
			</Button>
			<Modal title="Шаблоны" onClose={() => {setOpen(false)}} size="full" open={open}>
				dasd
			</Modal>
		</>
	);
}
