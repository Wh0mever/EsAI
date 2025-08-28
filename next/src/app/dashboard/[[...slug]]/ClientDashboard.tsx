"use client";

import "@/assets/style.scss";
import "../dashboard.scss";
import Chat from "@/components/chat/Chat";
import { fetchData } from "@/tools/fetchData";
import { useTranslation } from "react-i18next";
import { useState, useEffect } from "react";
import Sidebar from "@/components/chat/ChatAside";
import type { ChatMode } from "@/types/chat";

type Props = { slug: ChatMode; chatId?: string | null };

export default function ClientDashboard({ slug, chatId }: Props) {
	
	const [chatsList, setChatsList] = useState<any[]>([]);
	const { t } = useTranslation("dashboard");
	const { t: tCommon } = useTranslation("common");

	useEffect(() => {
		let isMounted = true;
		(async () => {
			try {
				const responseData = await fetchData("ai/sessions/", "get", null, true);
				if (isMounted) setChatsList(responseData?.data || []);
			} catch {
				if (isMounted) setChatsList([]);
			}
		})();
		return () => {
			isMounted = false;
		};
	}, []);



	return (
		<main className="antialiased mx-auto h-full flex bg-neutral-800/75 gap-5">
			<div className="w-3/12">
				<Sidebar chats={chatsList} />
			</div>

			<div className="flex w-6/12">
				<Chat mode={slug} chatId={chatId ?? undefined} />
			</div>

			<div className="w-3/12 flex items-start">
				<div className="flex items-center w-full justify-end gap-3 p-4">

				</div>
			</div>
		</main>
	);
}
