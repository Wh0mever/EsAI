"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { BACKEND } from "@/tools/fetchData";
import { Message } from "./ChatForm";
import { useTranslation } from "react-i18next";
import type { ChatMode } from "@/types/chat";

function isImageUrl(s: string): boolean {
	if (!s) return false;
	const lower = s.toLowerCase();
	if (lower.startsWith("/media/generated/") || lower.includes("/generated/")) return true;
	return /\.(png|jpe?g|webp|gif)(\?.*)?$/.test(lower);
}

type ChatViewProps = { messages: Message[]; mode: ChatMode; loading?: boolean; initialHydrated?: boolean; animateIndex?: number | null };

// types text char-by-char on mount
function TypingText({
	text,
	speed = 18,
	onDone,
	className = "",
}: {
	text: string;
	speed?: number; // ms per char
	onDone?: () => void;
	className?: string;
}) {
	const [i, setI] = useState(0);
	useEffect(() => {
		if (!text) {
			onDone?.();
			return;
		}
		let cancelled = false;
		const tick = () => {
			setI((v) => {
				const nv = Math.min(v + 1, text.length);
				if (nv === text.length) onDone?.();
				return nv;
			});
			if (!cancelled && i + 1 < text.length) {
				timer = window.setTimeout(tick, speed);
			}
		};
		let timer = window.setTimeout(tick, speed);
		return () => {
			cancelled = true;
			window.clearTimeout(timer);
		};
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [text, speed]);
	return <span className={className}>{text.slice(0, i)}</span>;
}

// animated "Thinking..." placeholder
function ThinkingDots({ text = "Думаю" }: { text?: string }) {
	const [n, setN] = useState(0);
	useEffect(() => {
		const id = setInterval(() => setN((v) => (v + 1) % 4), 450);
		return () => clearInterval(id);
	}, []);
	return (
		<span aria-live="polite">
			{text}
			{".".repeat(n)}
		</span>
	);
}

export function ChatView({ messages, mode, loading, initialHydrated, animateIndex }: ChatViewProps) {
	const wrapRef = useRef<HTMLDivElement | null>(null);
	const { t } = useTranslation("common");
	const isEmpty = !messages || messages.length === 0;

	// detect "thinking": last assistant message is missing or empty
	const last = messages[messages.length - 1];
    const isThinking =
        !messages.length || (last?.role === "assistant" && (!last.content || last.content.trim() === ""));

	// remember which message indices already animated
    const animatedRef = useRef<Set<number>>(new Set());
    const hydrationDoneRef = useRef<boolean>(false);
    const stickToBottomRef = useRef<boolean>(true); // only autoscroll if near bottom

    // Mark existing messages (e.g., history) as already animated to avoid replaying typing effect
    useEffect(() => {
        if (!initialHydrated || hydrationDoneRef.current) return;
        const set = animatedRef.current;
        for (let i = 0; i < messages.length; i++) {
            const m = messages[i];
            if (m?.role === "assistant" && m?.content) {
                // Keep one target index un-animated (to re-type) if requested
                if (typeof animateIndex === 'number' && i === animateIndex) continue;
                set.add(i);
            }
        }
        hydrationDoneRef.current = true;
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [initialHydrated, messages.length, animateIndex]);

	// autoscroll to bottom on new messages when user hasn't scrolled up
	const scrollToBottom = () => {
		const el = wrapRef.current;
		if (!el) return;
		el.scrollTop = el.scrollHeight;
	};
	useEffect(() => {
		if (stickToBottomRef.current) scrollToBottom();
	}, [messages.length]);

	const handleScroll = () => {
		const el = wrapRef.current;
		if (!el) return;
		const threshold = 64; // px from bottom considered near-bottom
		const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
		stickToBottomRef.current = distance <= threshold;
	};

	return (
		<div ref={wrapRef} onScroll={handleScroll} className="flex flex-col gap-4 overflow-y-auto max-h-[calc(100vh-300px)] pr-1">
			{isEmpty ? (
				<div className="flex-1 grid place-items-center min-h-[50vh]">
					<div className="text-center space-y-2">
						<h3 className="text-2xl text-white font-semibold">
							{mode === "text-chat"
								? t("chat.empty_text_title", { defaultValue: "Готов творить текст вместе с Vokalo?" })
								: t("chat.empty_image_title", {
										defaultValue: "Готов создавать изображения вместе с Vokalo?",
								  })}
						</h3>
						<p className="text-neutral-300">
							{mode === "text-chat"
								? t("chat.empty_text_subtitle", { defaultValue: "Тогда начнём!" })
								: t("chat.empty_image_subtitle", { defaultValue: "Тогда начнём!" })}
						</p>
					</div>
				</div>
			) : (
				messages.map((msg, index) => {
					const isUser = msg.role === "user";
					const bubbleClass = isUser
						? "self-end bg-indigo-700 text-white"
						: "self-start bg-neutral-900 text-white";

                    const shouldType =
                        // only assistants
                        !isUser &&
                        // only if content exists
                        !!msg.content &&
                        // only if not typed before
                        (!animatedRef.current.has(index) || (typeof animateIndex === 'number' && index === animateIndex));

					return (
						<div key={index} className={`p-4 rounded-xl max-w-[80%] whitespace-pre-wrap ${bubbleClass}`}>
							{/* render images when content looks like an image URL */}
							{!isUser && msg.content && isImageUrl(msg.content) ? (
								<img
									src={msg.content.startsWith("/") ? `${BACKEND}${msg.content}` : msg.content}
									alt="generated"
									className="max-w-full rounded-lg"
								/>
                            ) : !isUser && index === messages.length - 1 && isThinking ? (
                                <ThinkingDots text={t("chat.thinking", { defaultValue: "Думаю" })} />
                            ) : shouldType ? (
								<TypingText
									text={msg.content}
									speed={18}
									onDone={() => {
										animatedRef.current.add(index);
										// keep view pinned to bottom while finishing typing only if user near bottom
										if (stickToBottomRef.current) scrollToBottom();
									}}
								/>
							) : (
                                <span>{msg?.content ?? t("chat.thinking_ellipsis", { defaultValue: "Думаю…" })}</span>
                            )}
                        </div>
                    );
                })
            )}
            {/* If last is user and request is in-flight, show a trailing assistant bubble with thinking */}
            {messages.length > 0 && loading && last?.role === "user" && (
                <div className="p-4 rounded-xl max-w-[80%] whitespace-pre-wrap self-start bg-neutral-900 text-white">
                    <ThinkingDots text={t("chat.thinking", { defaultValue: "Думаю" })} />
                </div>
            )}
        </div>
    );
}
