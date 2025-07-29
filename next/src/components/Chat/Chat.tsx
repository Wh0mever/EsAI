"use client";

import { useState, useRef, useEffect, FormEvent, KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { Message, ChatForm } from "./ChatForm";
import { ChatView } from "./ChatView";


export default function Chat() {
	const [input, setInput] = useState("");
	const [messages, setMessages] = useState<Message[]>([]);
	const { t } = useTranslation("common");

	const handleSubmit = async (e: FormEvent) => {
		e.preventDefault();
		const content = input.trim();
		if (!content) return;

		const newMessage: Message = { role: "user", content };
		setMessages((prev) => [...prev, newMessage]);
		setInput("");

		 JSON.stringify({ message: content })

		try {
			const res = await fetchData("ai/chat/", "POST", { message: content }, true)
			.then((res) => {
				setInput("")
				setMessages((prev) => [
					...prev,
					{ role: "assistant", content: res?.data.response}
				])
			})
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
