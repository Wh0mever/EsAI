"use client";

import { Button } from "../UI/Buttons/Buttons";
import { form } from "framer-motion/client";
import { useState, useEffect } from "react";
import { FaPlus } from "react-icons/fa6";
import { VscSettings } from "react-icons/vsc";
import { TiMicrophoneOutline } from "react-icons/ti";
import { useRef } from "react";
import { useTranslation } from "react-i18next";

const languages = [
	{ code: "ru", icon: "/images/local/ru.webp" },
	{ code: "en", icon: "/images/local/en.webp" },
	{ code: "kg", icon: "/images/local/kg.webp" },
];


function ChatForm() {
	const textareaRef = useRef<HTMLTextAreaElement>(null);
	const { t } = useTranslation("common");

	const handleInput = () => {
		const el = textareaRef.current;
		if (el) {
			el.style.height = "auto";
			el.style.height = el.scrollHeight + "px";
		}
	};

	return (
		<form className="bg-neutral-900 chat-form p-5 rounded-3xl border border-neutral-800">
			<div className="w-full">
				<textarea
					ref={textareaRef}
					onInput={handleInput}
					className="w-full chat-textarea"
					placeholder={t("chat.ask_something")}
				/>
			</div>
			<div className="flex justify-between">
				<div className="flex gap-5 mt-4">
					<Button className="text-gray-200 hover:bg-neutral-700/50 text-xl bg-neutral-900 duration-300 p-3 rounded-full">
						<FaPlus />
					</Button>
					<Button className="text-gray-200 hover:bg-neutral-700/50 text-xl bg-neutral-900 duration-300 p-3 rounded-full">
						<VscSettings />
					</Button>
				</div>
				<div className="flex gap-5 mt-4">
					<Button className="text-gray-200 hover:bg-neutral-700/50 text-xl bg-neutral-900 duration-300 p-3 rounded-full">
						<TiMicrophoneOutline />
					</Button>
				</div>
			</div>
		</form>
	);
}

function ChatView() {
    return (
        <div className="">
            
        </div>
    )
}

export default function Chat() {
	return (
		<div className="h-full py-10 px-5 flex flex-col justify-between gap-3">
            <ChatView />
			<ChatForm />
		</div>
	);
}
