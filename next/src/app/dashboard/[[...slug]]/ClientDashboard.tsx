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
//
// showQuickPrompts: only here, not on `/` — the home page's start screen
// already has HomeHero + WhyEsAI above/around it, while this route (reached
// e.g. right after "Начать бесплатно" for an authenticated visitor) has
// nothing but a bare composer, which is why the product owner asked for the quick-prompt
// chips specifically here (24.07.2026), then asked to keep them off the
// home page the same day.
export default function ClientDashboard({ slug, chatId }: Props) {
	return <ChatWorkspace mode={slug} chatId={chatId ?? undefined} showQuickPrompts />;
}
