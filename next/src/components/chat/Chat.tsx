"use client";

import { useState, useRef, useEffect, FormEvent, KeyboardEvent } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { Message, ChatForm } from "./ChatForm";
import { ChatView } from "./ChatView";
import type { ChatMode as Mode } from "@/types/chat";

export type ChatMode = "text-chat" | "image-chat" | "music-chat";

type Props = {
  mode: ChatMode;
  chatId?: string; // optional
};

export default function Chat({ mode, chatId }: Props) {
  const router = useRouter();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [attachments, setAttachments] = useState<any[]>([]);
  const { t, i18n } = useTranslation("common");
  const [loading, setLoading] = useState(false);
  const [historyHydrated, setHistoryHydrated] = useState(false);
  const [animateIndex, setAnimateIndex] = useState<number | null>(null);

  // load history when chatId provided
  useEffect(() => {
    let ignore = false;
    setHistoryHydrated(false);
    const load = async () => {
      if (!chatId) return;
      try {
        const res = await fetchData(`ai/sessions/${chatId}/`, "GET", null, true);
        if (!ignore) {
          const history = res?.data?.messages as Message[] | undefined;
          if (Array.isArray(history)) {
            setMessages(history);
            setHistoryHydrated(true);
            // If we just created this session, animate the last assistant once
            try {
              const key = `chat.animate.${chatId}`;
              const shouldAnimate = typeof window !== 'undefined' ? sessionStorage.getItem(key) : null;
              if (shouldAnimate) {
                // find last assistant index to animate
                let lastAssistant = -1;
                for (let i = history.length - 1; i >= 0; i--) {
                  if (history[i]?.role === 'assistant' && (history[i]?.content || '').length > 0) {
                    lastAssistant = i;
                    break;
                  }
                }
                if (lastAssistant >= 0) setAnimateIndex(lastAssistant);
                if (typeof window !== 'undefined') sessionStorage.removeItem(key);
              } else {
                setAnimateIndex(null);
              }
            } catch {
              setAnimateIndex(null);
            }
          }
        }
      } catch {
        if (!ignore) setMessages([]);
      }
    };
    load();
    return () => {
      ignore = true;
    };
  }, [chatId]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const content = input.trim();
    if (!content) return;
    // Block submit while attachments still uploading
    if (attachments && attachments.some((a) => a && a.status === "uploading")) return;

    // Snapshot ready attachments for this request, then clear UI preview immediately
    const readyAttachments = (attachments || []).filter((a) => a && a.url);

    const newMessage: Message = { role: "user", content };
    setMessages((prev) => [...prev, newMessage]);
    setInput("");

    const templates = localStorage.getItem("ai-templates");

    // kept to avoid breaking behavior
    JSON.stringify({ message: content }); // no-op

    // Helper for localized error messages in the chat bubble
    const formatError = (res?: { ok?: boolean; status?: number; error?: string } | null): string => {
      const status = res?.status ?? 0;
      if (status === 0) return t("chat.error_network");
      if (status === 401) return t("chat.error_unauthorized");
      if (status === 403) return t("chat.error_forbidden");
      if (status === 404) return t("chat.error_notfound");
      if (mode === "image-chat") return t("chat.error_image_generation");
      return t("chat.error_request_failed");
    };

    try {
      setLoading(true);
      const payload: any = { message: content, templates: templates, mode: mode };
      if (chatId) payload.chat_id = chatId; // bind to existing session when provided
      if (readyAttachments.length) payload.attachments = readyAttachments;
      // pass current UI language to backend so it can respond in user's locale
      if (i18n?.language) payload.lang = i18n.language;

      // hide attachments preview immediately for snappy UX
      if (attachments && attachments.length) setAttachments([]);

      const endpoint = mode === "image-chat" ? "ai/image/" : "ai/chat/";
      const res = await fetchData(endpoint, "POST", payload, true);
      setInput("");

      // If request failed, push a localized error bubble and stop
      if (!res?.ok) {
        setMessages((prev) => [...prev, { role: "assistant", content: formatError(res), variant: "error" }]);
        return;
      }

      const sessionMeta = (res?.data?.session ?? null) as { id?: string; title?: string } | null;
      let assistantContent = "";
      if (mode === "image-chat") {
        assistantContent = (res?.data as any)?.image?.url || (res?.data as any)?.response || "";
      } else {
        assistantContent = (res?.data as any)?.response || "";
      }

      // If backend didn't provide output, show generic localized error instead of hanging "thinking"
      if (!assistantContent) {
        const msg = mode === "image-chat" ? t("chat.error_image_generation") : t("chat.error_generic");
        setMessages((prev) => [...prev, { role: "assistant", content: msg, variant: "error" }]);
      } else {
        setMessages((prev) => [...prev, { role: "assistant", content: assistantContent }]);
      }

      // If this was a new chat (no chatId before) and backend created a session, update URL and notify sidebar
      if (!chatId && sessionMeta && sessionMeta.id) {
        try {
          // mark to animate last assistant once after navigation
          if (typeof window !== 'undefined') {
            sessionStorage.setItem(`chat.animate.${sessionMeta.id}`, '1');
          }
          // update route to include the new chat id
          router.push(`/dashboard/${mode}/${sessionMeta.id}`);
        } catch {}
        try {
          window.dispatchEvent(
            new CustomEvent("chat:session-created", {
              detail: { id: sessionMeta.id, title: sessionMeta.title || content.slice(0, 60), chat_mode: mode },
            })
          );
        } catch {}
      }
      // already cleared before request; keep as is
    } catch (error) {
      console.error("Ошибка при обращении к /api/chat/:", error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-full py-2 lg:py-5 px-5 flex flex-col justify-between gap-3 w-full">
      <ChatView mode={mode as Mode} messages={messages} loading={loading} initialHydrated={historyHydrated} animateIndex={animateIndex ?? undefined} />
      <ChatForm
        input={input}
        setInput={setInput}
        handleSubmit={handleSubmit}
        messages={messages}
        setMessages={setMessages}
        attachments={attachments}
        setAttachments={setAttachments}
      />
    </div>
  );
}
