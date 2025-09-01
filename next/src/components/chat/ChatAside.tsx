"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { FiPlus, FiChevronLeft, FiChevronRight, FiSettings } from "react-icons/fi";
import { IoImages, IoLibrary } from "react-icons/io5";
import { FaRegUser } from "react-icons/fa";
import { CiMenuFries } from "react-icons/ci";
import NextLink from "@/components/ui/nextLink/NextLink";
import { Modal, ConfirmationModal } from "@/components/dialog/Dialog";
import { fetchData } from "@/tools/fetchData";
import { Button } from "../ui/buttons/Buttons";
import Cookies from "js-cookie";

type Chat = { id: string; title: string; href?: string; chat_mode: string };

type SidebarProps = {
	chats: Chat[];
	activeChatId?: string;
	onNewChat?: () => void;
	className?: string;
};

const LS_COLLAPSED = "sidebar.collapsed";

function SectionTitle({ children }: { children: React.ReactNode }) {
	return <div className="text-xs uppercase tracking-wide text-neutral-400">{children}</div>;
}

function NavBtn({
	icon,
	label,
	showText,
	onClick,
	title,
	counter = 0, // новый проп
}: {
	icon: React.ReactNode;
	label: string;
	showText: boolean;
	onClick?: () => void;
	title?: string;
	counter?: number;
}) {
	return (
		<button
			type="button"
			onClick={onClick}
			className="relative flex w-full items-center gap-3 rounded-md px-2 py-2 text-sm hover:bg-white/5 cursor-pointer"
			title={showText ? title : title ?? label}
		>
			<span className="shrink-0 opacity-70">{icon}</span>
			{showText && <span className="truncate">{label}</span>}
			{counter > 0 && (
				<span className="absolute right-2 top-1/2 -translate-y-1/2 bg-rose-600 text-white text-xs font-medium rounded-full px-1.5 py-0.5 min-w-[20px] text-center">
					{counter}
				</span>
			)}
		</button>
	);
}
function NavLink({
	icon,
	label,
	showText,
	href,
	title,
}: {
	icon: React.ReactNode;
	label: string;
	showText: boolean;
	href: string;
	title?: string;
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

/* Persist boolean in localStorage */
function usePersistentBoolean(key: string, initial = false) {
	const [value, setValue] = useState(initial);
	useEffect(() => {
		try {
			const raw = typeof window !== "undefined" ? localStorage.getItem(key) : null;
			if (raw !== null) setValue(raw === "1");
		} catch {}
	}, [key]);
	useEffect(() => {
		try {
			localStorage.setItem(key, value ? "1" : "0");
		} catch {}
	}, [key, value]);
	return [value, setValue] as const;
}

/* Ctrl/Cmd+B toggle */
function useToggleHotkey(cb: () => void) {
	useEffect(() => {
		const onKey = (e: KeyboardEvent) => {
			const isCmd = navigator.platform.includes("Mac") ? e.metaKey : e.ctrlKey;
			if (isCmd && e.key.toLowerCase() === "b") {
				e.preventDefault();
				cb();
			}
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [cb]);
}

/* Load notifications count */
function useNotificationsCount() {
	const [count, setCount] = useState(0);
	useEffect(() => {
		let cancelled = false;
		(async () => {
			try {
				const res = await fetchData("users/notifications/", "GET", null, true);
				if (!cancelled) setCount(Array.isArray(res?.data) ? res.data.length : 0);
			} catch {
				if (!cancelled) setCount(0);
			}
		})();
		return () => {
			cancelled = true;
		};
	}, []);
	return count;
}

/* Safe username from localStorage */
function useUsername() {
	const [user, setUser] = useState<string>("User");
	useEffect(() => {
		try {
			const raw = localStorage.getItem("user");
			const parsed = raw ? JSON.parse(raw) : {};
			setUser(parsed?.username || "User");
		} catch {
			setUser("User");
		}
	}, []);
	return user;
}

export default function Sidebar({ chats, activeChatId, onNewChat, className }: SidebarProps) {
	const { t } = useTranslation("common");
	const [collapsed, setCollapsed] = usePersistentBoolean(LS_COLLAPSED, false);
	const [showMobileAside, setShowMobileAside] = useState(false);
	const [settingsOpen, setSettingsOpen] = useState(false);
	const notificationsCount = useNotificationsCount();
	const username = useUsername();

	useToggleHotkey(() => setCollapsed((v) => !v));

	const width = collapsed ? "w-14" : "w-72";
	const showText = !collapsed;
	const [isLogoutConfirmModalOpen, setLogoutConfirmModalOpen] = useState(false);
	const handleNewChat = useCallback(() => {
		if (onNewChat) onNewChat();
	}, [onNewChat]);

	const handleLogoutConfirmModalOpen = () => {
		Cookies.remove("access");
		Cookies.remove("refresh");
		Cookies.remove("user");
		window.location.href = "/auth/signin";
	};

	return (
		<>
			<div className="lg:hidden">
				<Button
					className="text-3xl px-2 py-2"
					onClick={() => {
						setCollapsed(false); // expand content on mobile
						setShowMobileAside(true);
					}}
				>
					<CiMenuFries />
				</Button>

				{showMobileAside && (
					<div className="fixed inset-0 z-[1000]">
						{/* backdrop */}
						<div className="absolute inset-0 bg-black/60" onClick={() => setShowMobileAside(false)} />
						{/* aside content */}
						<aside
							className={[
								"fixed inset-y-0 left-0 w-full h-full bg-neutral-900 text-neutral-100",
								"border-r border-white/10 transition-transform duration-300 ease-out",
								"flex flex-col",
							].join(" ")}
						>
							{/* header */}
							<div className="flex items-center justify-between px-2 py-2 shrink-0">
								<div className="flex items-center gap-2">
									<div className="grid place-items-center size-8">
										<img src="/images/logo/head.svg" alt="" />
									</div>
									<span className="text-sm font-medium">Vokalo</span>
								</div>
								<button
									className="p-2 rounded-md hover:bg-white/10 cursor-pointer"
									onClick={() => setShowMobileAside(false)}
									title="Close"
								>
									<FiChevronLeft />
								</button>
							</div>

							{/* tools */}
							<div className="px-2 py-1 shrink-0 space-y-1">
								<NavLink
									href="/dashboard/text-chat/"
									icon={<FiPlus />}
									label={t("chat.new_chat")}
									showText={true}
									title={`${t("chat.new_chat")} (Ctrl/Cmd+B to toggle sidebar)`}
								/>
								<NavBtn icon={<IoImages />} label={"DALL·E"} showText={true} onClick={handleNewChat} />
								<NavBtn icon={<IoLibrary />} label={t("chat.lib")} showText={true} onClick={() => {}} />
							</div>

							{/* chats */}
							<div className="px-2 pt-2 flex-1 min-h-0 flex flex-col">
								<SectionTitle>{t("chat.chat_history")}</SectionTitle>
								<ul className="mt-1 space-y-1 overflow-y-auto pr-1 flex-1">
									{chats.length > 0 &&
										chats.map((c) => (
											<li key={c.id}>
												<NextLink
													href={`/dashboard/${c.chat_mode}/${c.id}`}
													className={[
														"block rounded-md px-2 py-2 text-sm truncate",
														c.id === activeChatId ? "bg-white/10" : "hover:bg-white/5",
													].join(" ")}
													onClick={() => setShowMobileAside(false)}
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

							{/* footer / settings */}
							<div className="px-2 py-2 border-t border-white/10 shrink-0">
								<NavLink icon={<FaRegUser />} label={username} href="/profile" showText={true} />
								<NavBtn
									icon={<FiSettings />}
									label={t("common.settings")}
									showText={true}
									onClick={() => {
										setSettingsOpen(true);
										setShowMobileAside(false);
									}}
									title={t("common.settings")}
									counter={notificationsCount}
								/>
							</div>
						</aside>
					</div>
				)}
			</div>

			{/* aside виден только на lg и выше */}
			<aside
				className={[
					"hidden lg:flex fixed left-0 top-0 h-dvh bg-neutral-900 text-neutral-100 border-r border-white/10",
					"transition-[width] duration-300 ease-out flex-col",
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
						title={`${t("chat.new_chat")} (Ctrl/Cmd+B to toggle sidebar)`}
					/>
					<NavBtn icon={<IoImages />} label={"DALL·E"} showText={showText} onClick={handleNewChat} />
					<NavBtn icon={<IoLibrary />} label={t("chat.lib")} showText={showText} onClick={() => {}} />
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
											href={`/dashboard/${c.chat_mode}/${c.id}`}
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

				{/* footer / settings */}
				<div className="px-2 py-2 border-t border-white/10 shrink-0">
					<NavLink icon={<FaRegUser />} label={username} href="/profile" showText={showText} />
					<NavBtn
						icon={<FiSettings />}
						label={t("common.settings")}
						showText={showText}
						onClick={() => setSettingsOpen(true)}
						title={t("common.settings")}
						counter={notificationsCount}
					/>
				</div>

				{/* Settings Modal */}
				<Modal
					title={t("common.settings")}
					open={settingsOpen}
					onClose={() => setSettingsOpen(false)}
					size="md"
				>
					<div className="space-y-4">
						<div className="flex items-center justify-between">
							<div className="text-sm text-neutral-300">{t("common.notifications")}</div>
							<div className="text-sm font-medium">{notificationsCount}</div>
						</div>

						<div className="flex items-center justify-between">
							<div className="text-sm text-neutral-300">{t("chat.collapse_sidebar")}</div>
							<button
								className="px-3 py-1 rounded-md bg-white/10 hover:bg-white/15 text-sm"
								onClick={() => setCollapsed((v) => !v)}
							>
								{collapsed ? t("common.no") : t("common.yes")}
							</button>
						</div>

						<div className="flex items-center justify-between">
							<div className="text-sm text-neutral-300">{t("common.language")}</div>
							<div className="flex gap-2">
								<LangBtn code="ru" />
								<LangBtn code="en" />
								<LangBtn code="kg" />
							</div>
						</div>

						<Button
							className="bg-rose-700 text-white px-4 py-2 rounded-lg"
							onClick={() => {
								setLogoutConfirmModalOpen(true);
								setShowMobileAside(false);
								setSettingsOpen(false);
							}}
						>
							{t("nav.logout")}
						</Button>
					</div>
				</Modal>
			</aside>
			{/* Exit confirmation Modal */}
			<ConfirmationModal
				isOpen={isLogoutConfirmModalOpen}
				title={t("nav.logOutConfirmTitle")}
				confirmText={t("common.yes")}
				cancelText={t("common.no")}
				onConfirm={handleLogoutConfirmModalOpen}
				onCancel={() => setLogoutConfirmModalOpen(false)}
			/>
		</>
	);
}

function LangBtn({ code }: { code: "ru" | "en" | "kg" }) {
	const { i18n } = useTranslation();
	const active = i18n.language === code;
	return (
		<button
			onClick={() => i18n.changeLanguage(code)}
			className={[
				"px-3 py-1 rounded-md text-sm transition",
				active ? "bg-white/20" : "bg-white/10 hover:bg-white/15",
			].join(" ")}
		>
			{code.toUpperCase()}
		</button>
	);
}
