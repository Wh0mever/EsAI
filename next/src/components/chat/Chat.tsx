"use client";

import { useState, useRef, useEffect, FormEvent, KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { Message, ChatForm } from "./ChatForm";
import { ChatView } from "./ChatView";

export type ChatMode = "text-chat" | "image-chat" | "music-chat";

type Props = {
  mode: ChatMode;
  chatId?: string; // optional
};

export default function Chat({ mode, chatId }: Props) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
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

    const newMessage: Message = { role: "user", content };
    setMessages((prev) => [...prev, newMessage]);
    setInput("");

    const templates = localStorage.getItem("ai-templates");

    // kept to avoid breaking behavior
    JSON.stringify({ message: content }); // no-op

    try {
      const payload: any = { message: content, templates: templates, mode: mode };
      if (chatId) payload.chat_id = chatId; // bind to existing session when provided

      const res = await fetchData("ai/chat/", "POST", payload, true);
      setInput("");
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: res?.data?.response },
      ]);
    } catch (error) {
      console.error("Ошибка при обращении к /api/chat/:", error);
    }
  };

  return (
    <div className="h-full py-5 px-5 flex flex-col justify-between gap-3 w-full">
      <ChatView messages={messages} />
      <ChatForm
        input={input}
        setInput={setInput}
        handleSubmit={handleSubmit}
        messages={messages}
        setMessages={setMessages}
      />
    </div>
  );
}
