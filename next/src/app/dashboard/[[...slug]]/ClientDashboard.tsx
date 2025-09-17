"use client";

import "@/assets/style.scss";
import "../dashboard.scss";
import Chat from "@/components/chat/Chat";
import { fetchData } from "@/tools/fetchData";
import { useState, useEffect } from "react";
import Sidebar from "@/components/chat/ChatAside";
import type { ChatMode } from "@/types/chat";

type Props = { slug: ChatMode; chatId?: string | null };

export default function ClientDashboard({ slug, chatId }: Props) {
	
	const [chatsList, setChatsList] = useState<any[]>([]);

  useEffect(() => {
    let isMounted = true;
    void (async () => {
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

  // Listen for new session creation to update sidebar immediately
  useEffect(() => {
    const onCreated = (e: any) => {
      const d = e?.detail;
      if (!d || !d.id) return;
      setChatsList((prev) => {
        const exists = Array.isArray(prev) && prev.some((c: any) => String(c.id) === String(d.id));
        if (exists) return prev;
        const item = { id: d.id, title: d.title || "New Chat", chat_mode: d.chat_mode || slug };
        return [item, ...(Array.isArray(prev) ? prev : [])];
      });
    };
    window.addEventListener("chat:session-created", onCreated as any);
    return () => window.removeEventListener("chat:session-created", onCreated as any);
  }, [slug]);



	return (
		<main  className="antialiased h-screen relative mx-auto max-h-screen flex bg-neutral-800/75 gap-5">
      <div className="lg:w-3/12 lg:static absolute left-0 top-0 p-2">
        <Sidebar chats={chatsList} activeChatId={chatId ?? undefined} />
      </div>

			<div className="flex lg:w-6/12 w-full">
				<Chat mode={slug} chatId={chatId ?? undefined} />
			</div>
		</main>
	);
}
