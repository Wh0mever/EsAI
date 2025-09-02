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
		<main  className="antialiased h-screen relative mx-auto max-h-screen flex bg-neutral-800/75 gap-5">
			<div className="lg:w-3/12 lg:static absolute left-0 top-0 p-2">
				<Sidebar chats={chatsList} />
			</div>

			<div className="flex lg:w-6/12 w-full">
				<Chat mode={slug} chatId={chatId ?? undefined} />
			</div>
		</main>
	);
}
