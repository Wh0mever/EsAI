"use client";

import "@/assets/style.scss";
import "../dashboard.scss";
import ChatWorkspace from "@/components/chat/ChatWorkspace";
import type { ChatMode } from "@/types/chat";

type Props = { slug: ChatMode; chatId?: string | null };

// The dashboard now reuses the same full EsAI chat workspace as `/`, so the
// experience (sidebar, balance, models, markdown) is identical everywhere.
// Existing routes like /dashboard/text-chat/<id> keep working and hydrate the
// given session.
export default function ClientDashboard({ slug, chatId }: Props) {
	return <ChatWorkspace mode={slug} chatId={chatId ?? undefined} />;
}
