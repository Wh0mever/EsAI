"use client";

import { useState, useRef, useEffect, FormEvent, KeyboardEvent } from "react";
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
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [attachments, setAttachments] = useState<any[]>([]);
  const { t } = useTranslation("common");

  // load history when chatId provided
  useEffect(() => {
    let ignore = false;
    const load = async () => {
      if (!chatId) return;
      try {
        const res = await fetchData(`ai/sessions/${chatId}/`, "GET", null, true);
        if (!ignore) {
          const history = res?.data?.messages as Message[] | undefined;
          if (Array.isArray(history)) setMessages(history);
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

    const newMessage: Message = { role: "user", content };
    setMessages((prev) => [...prev, newMessage]);
    setInput("");

    const templates = localStorage.getItem("ai-templates");

    // kept to avoid breaking behavior
    JSON.stringify({ message: content }); // no-op

    try {
      const payload: any = { message: content, templates: templates, mode: mode };
      if (chatId) payload.chat_id = chatId; // bind to existing session when provided
      if (attachments && attachments.length)
        payload.attachments = attachments.filter((a) => a && a.url);

      const endpoint = mode === "image-chat" ? "ai/image/" : "ai/chat/";
      const res = await fetchData(endpoint, "POST", payload, true);
      setInput("");
      const assistantContent =
        mode === "image-chat"
          ? (res?.data?.image?.url || res?.data?.response || "")
          : (res?.data?.response || "");
      setMessages((prev) => [...prev, { role: "assistant", content: assistantContent }]);
      setAttachments([]);
    } catch (error) {
      console.error("Ошибка при обращении к /api/chat/:", error);
    }
  };

  return (
    <div className="h-full py-5 px-5 flex flex-col justify-between gap-3 w-full">
      <ChatView mode={mode as Mode} messages={messages} />
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
