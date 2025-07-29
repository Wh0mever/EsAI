"use client";

import "@/assets/style.scss";
import "./dashboard.scss";
import Chat from "@/components/Chat/Chat";
import DashboardNav from "@/components/Nav/DashboardNav";
import Cookies from "js-cookie";
import { useTranslation } from "react-i18next";
import { VscBell } from "react-icons/vsc";
import { Button } from "@/components/UI/Buttons/Buttons";
import { useState, useRef, useEffect } from "react";
import Dropdown from "@/components/DropDown/DropDown";
import { ConfirmationModal } from "@/components/Dialog/Dialog";

const currencyItems = [
	{ label: "KGS", value: "kgs" },
	{ label: "USD", value: "usd" },
	{ label: "EUR", value: "eur" },
];

const languageItems = [
	{ label: "Русский", value: "ru", icon: "/images/local/ru.webp" },
	{ label: "English", value: "en", icon: "/images/local/en.webp" },
	{ label: "Кыргызча", value: "kg", icon: "/images/local/kg.webp" },
];

export default function Dashboard() {
	const [openDropdown, setOpenDropdown] = useState<null | "lang" | "currency" | "notify">(null);
	const [selectedCurrency, setSelectedCurrency] = useState(currencyItems[0]);
	const [isLogoutConfirmModalOpen, setLogoutConfirmModalOpen] = useState(false);
	const { t } = useTranslation("dashboard");
	const { t: tCommon } = useTranslation("common");

	const currentLang = Cookies.get("NEXT_LOCALE") || "ru";

	const handleLangSelect = (lang: (typeof languageItems)[0]) => {
		Cookies.set("NEXT_LOCALE", lang.value);
		window.location.reload();
	};
	const handleLogoutConfirmModalOpen = () => {
		Cookies.remove("access");
		Cookies.remove("refresh");
		Cookies.remove("user");
		window.location.href = "/auth/signin";
	};

	const notificationItems = [{ label: "Уведомление 1" }, { label: "Уведомление 2" }, { label: "Уведомление 3" }];

	const isOpen = (name: typeof openDropdown) => openDropdown === name;
	const toggle = (name: typeof openDropdown) => (isOpen(name) ? setOpenDropdown(null) : setOpenDropdown(name));

	return (
		<main className="antialiased mx-auto h-full flex bg-neutral-800/75 gap-5">
			<div className="w-3/12">
				<DashboardNav />
			</div>
			<div className="flex w-6/12">
				<Chat />
			</div>
			<div className="w-3/12 flex items-start">
				<div className="flex items-center w-full justify-end gap-3 p-4">
					<Dropdown
						items={notificationItems}
						isOpen={isOpen("notify")}
						close={() => setOpenDropdown(null)}
						onSelect={() => {}}
						renderButton={(_, open, toggleBtn) => (
							<Button
								onClick={() => toggle("notify")}
								className="text-white p-1 rounded-md hover:text-indigo-700 bg-neutral-800"
							>
								<VscBell className="chat-button-icon" />
							</Button>
						)}
						renderItem={(item) => <>{item.label}</>}
					/>

					<Dropdown
						items={languageItems}
						isOpen={isOpen("lang")}
						close={() => setOpenDropdown(null)}
						onSelect={handleLangSelect}
						renderButton={(_, open) => (
							<button
								onClick={() => toggle("lang")}
								className="text-white rounded-md hover:text-indigo-500 bg-neutral-800 py-2 px-3 cursor-pointer transition flex items-center gap-2"
							>
								<img src={`/images/local/${currentLang}.webp`} className="h-5 p-1" alt="" />
							</button>
						)}
						renderItem={(item) => <img src={item.icon!} alt={item.label} className="w-full p-1" />}
					/>

					<Dropdown
						items={currencyItems}
						selected={selectedCurrency}
						setSelected={setSelectedCurrency}
						isOpen={isOpen("currency")}
						close={() => setOpenDropdown(null)}
						onSelect={() => {}}
						renderButton={(selected, open) => (
							<button
								onClick={() => toggle("currency")}
								className="text-white rounded-md hover:text-indigo-500 bg-neutral-800 py-2 px-3 cursor-pointer transition flex items-center gap-2"
							>
								{selected?.label || "KGS"}
							</button>
						)}
						renderItem={(item) => <>{item.label}</>}
					/>

					<Button
						className="bg-rose-700 text-white px-4 py-2 rounded"
						onClick={() => setLogoutConfirmModalOpen(true)}
					>
						{t("nav.logout")}
					</Button>

					<ConfirmationModal
						isOpen={isLogoutConfirmModalOpen}
						title={t("nav.logOutConfirmTitle")}
						confirmText={tCommon("common.yes")}
						cancelText={tCommon("common.no")}
						onConfirm={handleLogoutConfirmModalOpen}
						onCancel={() => setLogoutConfirmModalOpen(false)}
					/>
				</div>
			</div>
		</main>
	);
}
