import { Button } from "@/components/UI/Buttons/Buttons";
import { CiMenuFries } from "react-icons/ci";
import { BsFeather } from "react-icons/bs";
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { IoLibraryOutline } from "react-icons/io5";
import Link from "next/link";

function NavToggleButton() {
	return (
		<Button className="relative w-10 h-10 group flex items-center justify-center">
			<img
				src="/images/logo/head.svg"
				alt=""
				className="chat-button-icon absolute inset-0 transition-opacity duration-300 opacity-100 group-hover:opacity-0 left-1/2 top-1/2 transform -translate-x-1/2 -translate-y-1/2"
			/>
			<i className="flex justify-center items-center chat-button-icon absolute inset-0 transition-opacity duration-300 opacity-0 group-hover:opacity-100 text-indigo-500 left-1/2 top-1/2 transform -translate-x-1/2 -translate-y-1/2">
				<CiMenuFries />
			</i>
		</Button>
	);
}

export default function DashboardNav() {

	const { t } = useTranslation("common");

	return (
		<nav className="w-fit py-6 px-3 border-e bg-neutral-900 border-neutral-900 h-full flex flex-col gap-10 items-center">
			<NavToggleButton />

			<ul className="flex flex-col w-full h-fit gap-5 justify-center items-center">
				<li>
					<Link href={"/"} className="chat-button-icon hover:text-indigo-500 duration-300 relative">
						<BsFeather />
						<span className="btn-description">{t('chat.new_chat')}</span>
					</Link>
				</li>
				<li>
					<Link href={"/"} className="chat-button-icon hover:text-indigo-500 duration-300 relative">
						<IoLibraryOutline />
						<span className="btn-description">{t('chat.chat_history')}</span>
					</Link>
				</li>
			</ul>
		</nav>
	);
}
