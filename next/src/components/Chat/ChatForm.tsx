"use client";

import { useState, useRef, useEffect, FormEvent, KeyboardEvent } from "react";
import { Button } from "../UI/Buttons/Buttons";
import { VscSettings } from "react-icons/vsc";
import { TiMicrophoneOutline } from "react-icons/ti";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { IoIosSend, IoIosAttach } from "react-icons/io";
import AiTemplates from "./ChatTemplates";
import { FaImages } from "react-icons/fa6";
import { FaItunesNote } from "react-icons/fa6";
import { IoChatbubbleOutline } from "react-icons/io5";

export type Message = {
	role: "user" | "assistant";
	content: string;
};

export function ChatForm({
	input,
	setInput,
	handleSubmit,
	messages,
	setMessages,
}: {
	input: string;
	setInput: (val: string) => void;
	handleSubmit: (e: FormEvent) => void;
	messages: Message[];
	setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
}) {
	const textareaRef = useRef<HTMLTextAreaElement>(null);
	const { t } = useTranslation("common");

	const handleInput = () => {
		const el = textareaRef.current;
		if (el) {
			el.style.height = "auto";
			el.style.height = el.scrollHeight + "px";
		}
	};

	const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
		if (e.key === "Enter" && !e.shiftKey) {
			e.preventDefault();
			handleSubmit(e as any);
		}
	};

	useEffect(() => {
		handleInput();
	}, [input]);

	return (
		<div className="flex flex-col gap-2">
			<form
				onSubmit={handleSubmit}
				className="bg-neutral-900 chat-form p-5 rounded-3xl border border-neutral-800 w-full"
			>
				<div className="w-full">
					<textarea
						ref={textareaRef}
						onInput={handleInput}
						onKeyDown={handleKeyDown}
						value={input}
						onChange={(e) => setInput(e.target.value)}
						className="w-full chat-textarea resize-none overflow-hidden"
						rows={1}
						placeholder={t("chat.ask_something")}
					/>
				</div>
				<div className="flex justify-between">
					<div className="flex gap-1 mt-4">
						<Button
							type="button"
							className="text-gray-200 hover:bg-neutral-700/50 text-xl bg-neutral-900 duration-300 p-3 rounded-full"
							description={t("chat.attachments")}
						>
							<IoIosAttach />
						</Button>
						<AiTemplates />
						<Button
							type="button"
							className="text-gray-200 hover:bg-neutral-700/50 text-xl bg-neutral-900 duration-300 p-3 rounded-full"
							description={t("chat.settings")}
						>
							<VscSettings />
						</Button>
					</div>
					<div className="flex gap-1 mt-4">
						<Button
							type="button"
							className="text-gray-200 hover:bg-neutral-700/50 text-xl bg-neutral-900 duration-300 p-3 rounded-full"
							description={t("chat.voice_enter")}
						>
							<TiMicrophoneOutline />
						</Button>
						<Button
							type="submit"
							className="text-gray-200 hover:bg-neutral-700/50 text-xl bg-neutral-900 duration-300 p-3 rounded-full"
							description={t("chat.send")}
						>
							<IoIosSend />
						</Button>
					</div>
				</div>
			</form>

			<div className="w-full flex gap-3 justify-between items-center">
				<Button className="px-3 py-2 bg-neutral-900 flex-grow rounded-2xl border border-neutral-800 hover:bg-neutral-700/50 flex items-center justify-center gap-2">
					<i className="text-xl"><IoChatbubbleOutline /></i>
					<span>{t("chat.models_tabs.text")}</span>
				</Button>
				<Button className="px-3 py-2 bg-neutral-900 flex-grow rounded-2xl border border-neutral-800 hover:bg-neutral-700/50 flex items-center justify-center gap-2">
					<i className="text-xl"><FaImages /></i>
					<span>{t("chat.models_tabs.image")}</span>
				</Button>
				<Button className="px-3 py-2 bg-neutral-900 flex-grow rounded-2xl border border-neutral-800 hover:bg-neutral-700/50 flex items-center justify-center gap-2">
					<i className="text-xl"><FaItunesNote /></i>
					<span>{t("chat.models_tabs.music")}</span>
				</Button>
			</div>
		</div>
	);
}
