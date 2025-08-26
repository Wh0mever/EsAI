import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiPlus, FiSearch, FiBook, FiSettings, FiChevronLeft, FiChevronRight, FiStar } from "react-icons/fi";
import { IoImages, IoLibrary } from "react-icons/io5";
import { CiUser } from "react-icons/ci";
import NextLink from "../ui/nextLink/NextLink";
import { FaRegUser } from "react-icons/fa";
import { fetchData } from "@/tools/fetchData";

type Chat = { id: string; title: string; href?: string; chat_mode: string };

type SidebarProps = {
	chats: Chat[];
	activeChatId?: string;
	onNewChat?: () => void;
	className?: string;
};

const LS_KEY = "sidebar.collapsed";

export default function Sidebar({ chats, activeChatId, onNewChat, className }: SidebarProps) {
	const [collapsed, setCollapsed] = useState(false);
	const [notificationsCount, setNotificationsCount] = useState(0);
	const { t } = useTranslation("common");
	const user = JSON.parse(localStorage.getItem("user") || "{}").username || "User";

	useEffect(() => {
		const raw = localStorage.getItem(LS_KEY);
		if (raw) setCollapsed(raw === "1");
	}, []);
	useEffect(() => {
		localStorage.setItem(LS_KEY, collapsed ? "1" : "0");
	}, [collapsed]);

	useEffect(() => {
		(async () => {
			const responseData = await fetchData("users/notifications/", "get", null, true);
			setNotificationsCount(responseData?.data.length);
		})();
	}, [setNotificationsCount]);

	// toggle hotkey ctrl/cmd+b
	useEffect(() => {
		const onKey = (e: KeyboardEvent) => {
			const isCmd = navigator.platform.includes("Mac") ? e.metaKey : e.ctrlKey;
			if (isCmd && e.key.toLowerCase() === "b") {
				e.preventDefault();
				setCollapsed((v) => !v);
			}
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, []);

	const width = collapsed ? "w-14" : "w-72";
	const showText = !collapsed;

	return (
		<aside
			className={[
				"fixed left-0 top-0 h-dvh bg-neutral-900 text-neutral-100 border-r border-white/10",
				"transition-[width] duration-300 ease-out flex flex-col",
				width,
				className || "",
			].join(" ")}
		>
			{/* header */}
			<div className="flex items-center justify-between px-2 py-2 shrink-0">
				<div className="flex items-center gap-2">
					<div className="grid place-items-center size-8">
						<img src="/images/logo/head.svg" alt="" />
					</div>
					{showText && <span className="text-sm font-medium">Vokalo</span>}
				</div>
				<button
					className="p-2 rounded-md hover:bg-white/10 cursor-pointer"
					onClick={() => setCollapsed((v) => !v)}
					title={collapsed ? t("chat.expand_sidebar") : t("chat.collapse_sidebar")}
				>
					{collapsed ? <FiChevronRight /> : <FiChevronLeft />}
				</button>
			</div>

			{/* tools */}
			<div className="px-2 py-1 shrink-0 space-y-1">
				<NavLink
					href="/dashboard/text-chat/"
					icon={<FiPlus />}
					label={t("chat.new_chat")}
					showText={showText}
				/>
				<NavBtn icon={<IoImages />} label={"DELL-E"} showText={showText} />
				<NavBtn icon={<IoLibrary />} label={t("chat.lib")} showText={showText} />
			</div>

			{/* chats */}
			{!collapsed && (
				<div className="px-2 pt-2 flex-1 min-h-0 flex flex-col">
					<SectionTitle>{t("chat.chat_history")}</SectionTitle>
					<ul className="mt-1 space-y-1 overflow-y-auto pr-1 flex-1">
						{chats.length > 0 &&
							chats.map((c) => (
								<li key={c.id}>
									<NextLink
										href={`/dashboard/${c.chat_mode}/${c.id}` || "#"}
										className={[
											"block rounded-md px-2 py-2 text-sm truncate",
											c.id === activeChatId ? "bg-white/10" : "hover:bg-white/5",
										].join(" ")}
									>
										{c.title}
									</NextLink>
								</li>
							))}
						{chats.length === 0 && (
							<li>
								<span className="text-sm text-neutral-500 italic select-none">
									{t("chat.chats_list_empty")}
								</span>
							</li>
						)}
					</ul>
				</div>
			)}

			{/* settings */}
			<div className="px-2 py-2 border-t border-white/10 shrink-0">
				<NavLink icon={<FaRegUser />} label={user ? user : ""} href="/profile" showText={showText} />
				<NavBtn icon={<FiSettings />} label={t("common.settings")} showText={showText} />
			</div>
		</aside>
	);
}

/* helpers */
function SectionTitle({ children }: { children: React.ReactNode }) {
	return <div className="text-xs uppercase tracking-wide text-neutral-400">{children}</div>;
}

function NavBtn({
	icon,
	label,
	showText,
	onClick,
}: {
	icon: React.ReactNode;
	label: string;
	showText: boolean;
	onClick?: () => void;
}) {
	return (
		<button
			type="button"
			onClick={onClick}
			className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-sm hover:bg-white/5 cursor-pointer"
			title={showText ? undefined : label}
		>
			<span className="shrink-0 opacity-70">{icon}</span>
			{showText && <span className="truncate">{label}</span>}
		</button>
	);
}

function NavLink({
	icon,
	label,
	showText,
	href,
}: {
	icon: React.ReactNode;
	label: string;
	showText: boolean;
	href: string;
}) {
	return (
		<NextLink
			className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-sm hover:bg-white/5 cursor-pointer"
			href={href}
		>
			<span className="shrink-0 opacity-70">{icon}</span>
			{showText && <span className="truncate">{label}</span>}
		</NextLink>
	);
}
