"use client";

import "@/assets/style.scss";
import "./dashboard.scss";
import Chat from "@/components/chat/Chat";
import Cookies from "js-cookie";
import { useTranslation } from "react-i18next";
import { VscBell } from "react-icons/vsc";
import { Button } from "@/components/ui/buttons/Buttons";
import { useState, useRef, useEffect } from "react";
import Dropdown from "@/components/dropDown/DropDown";
import { ConfirmationModal } from "@/components/dialog/Dialog";
import Link from "next/link";
import { CiUser } from "react-icons/ci";
const languageItems = [
	{ label: "Русский", value: "ru", icon: "/images/local/ru.webp" },
	{ label: "English", value: "en", icon: "/images/local/en.webp" },
	{ label: "Кыргызча", value: "kg", icon: "/images/local/kg.webp" },
];

export default function Dashboard() {
	const [openDropdown, setOpenDropdown] = useState<null | "lang" | "currency" | "notify">(null);
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
				
			</div>
			<div className="flex w-6/12">
				<Chat />
			</div>
			<div className="w-3/12 flex items-start">
				<div className="flex items-center w-full justify-end gap-3 p-4">
					<Link className="chat-button-icon bg-neutral-800 text-xl hover:text-indigo-500 rounded-lg" href={"/profile"}>
						<i>
							<CiUser />
						</i>
					</Link>

					<Dropdown
						items={notificationItems}
						isOpen={isOpen("notify")}
						close={() => setOpenDropdown(null)}
						onSelect={() => {}}
						renderButton={(_, open, toggleBtn) => (
							<Button onClick={() => toggle("notify")} className="chat-button-icon bg-neutral-800 text-xl hover:text-indigo-500 rounded-lg">
								<i>
									<VscBell />
								</i>
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
							<Button onClick={() => toggle("lang")} className="chat-button-icon bg-neutral-800 text-xl hover:text-indigo-500 rounded-lg">
								<img src={`/images/local/${currentLang}.webp`} className="h-5 p-1" alt="" />
							</Button>
						)}
						renderItem={(item) => <img src={item.icon!} alt={item.label} className="w-full p-1" />}
					/>

					<Button
						className="bg-rose-700 text-white px-4 py-2 rounded-lg"
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
