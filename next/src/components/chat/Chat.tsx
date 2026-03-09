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

type MusicLanguage = "ru" | "en" | "kg";
type MusicTrackType = "instrumental" | "song";

function normalizeMusicLanguage(raw?: string): MusicLanguage {
  const base = (raw || "ru").toLowerCase().split("-")[0];
  if (base === "en") return "en";
  if (base === "kg" || base === "ky") return "kg";
  return "ru";
}

export default function Chat({ mode, chatId }: Props) {
  const router = useRouter();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [attachments, setAttachments] = useState<any[]>([]);
  const { t, i18n } = useTranslation("common");
  const [loading, setLoading] = useState(false);
  const [historyHydrated, setHistoryHydrated] = useState(false);
  const [animateIndex, setAnimateIndex] = useState<number | null>(null);
  const [musicLanguage, setMusicLanguage] = useState<MusicLanguage>(() => normalizeMusicLanguage(i18n?.language));
  const [musicGenre, setMusicGenre] = useState("pop");
  const [musicTrackType, setMusicTrackType] = useState<MusicTrackType>("instrumental");

  useEffect(() => {
    if (mode !== "music-chat") return;
    setMusicLanguage(normalizeMusicLanguage(i18n?.language));
  }, [i18n?.language, mode]);

  // load history when chatId provided
  useEffect(() => {
    let ignore = false;
    setHistoryHydrated(false);
    const load = async () => {
      if (!chatId) return;
      try {
        const res = await fetchData(`ai/sessions/${chatId}/`, "GET", null, true);
        if (!ignore) {
          const history =
            (res?.data?.messages as Message[] | undefined)
            || (res?.data?.results?.messages as Message[] | undefined);
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

    const newMessage: Message = { role: "user", content, attachments: readyAttachments?.length ? [...readyAttachments] : undefined };
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
      if (mode === "music-chat") return t("chat.error_music_generation");
      return t("chat.error_request_failed");
    };

    try {
      setLoading(true);
      const payload: any = { message: content, templates: templates, mode: mode };
      if (chatId) payload.chat_id = chatId; // bind to existing session when provided
      if (readyAttachments.length) payload.attachments = readyAttachments;
      // pass current UI language to backend so it can respond in user's locale
      if (mode === "music-chat") payload.lang = musicLanguage;
      else if (i18n?.language) payload.lang = i18n.language;

      // hide attachments preview immediately for snappy UX
      if (attachments && attachments.length) setAttachments([]);

      if (mode === "image-chat" || mode === "music-chat") {
        // Async pattern: submit job then poll status
        const submitEndpoint = mode === "image-chat" ? "ai/image/submit/" : "ai/music/submit/";
        const statusEndpoint = mode === "image-chat" ? "ai/image/status/" : "ai/music/status/";
        const submitPayload = mode === "music-chat"
          ? {
              ...payload,
              prompt: content,
              title: "Track",
              lyrics: "",
              is_auto: 1,
              instrumental: musicTrackType === "instrumental" ? 1 : 0,
              language: musicLanguage,
              genre: musicGenre,
            }
          : payload;

        const submit = await fetchData(submitEndpoint, "POST", submitPayload, true);
        setInput("");
        if (!submit?.ok || !(submit?.data as any)?.job_id) {
          setMessages((prev) => [...prev, { role: "assistant", content: formatError(submit), variant: "error" }]);
          return;
        }
        const jobId = (submit.data as any).job_id as string;

        // Poll until done (music can take noticeably longer)
        const startedAt = Date.now();
        const maxMs = mode === "music-chat" ? 10 * 60 * 1000 : 5 * 60 * 1000;
        const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));
        let finalUrl = "";
        let sessionMeta: { id?: string; uid?: string; title?: string } | null = null;
        while (Date.now() - startedAt < maxMs) {
          const st = await fetchData(`${statusEndpoint}?job=${encodeURIComponent(jobId)}`, "GET", null, true);
          if (!st?.ok) { await delay(1500); continue; }
          const status = (st.data as any)?.status;
          if (status === "SUCCESS") {
            const result = (st.data as any)?.result || {};
            finalUrl = mode === "music-chat" ? (result?.music?.url || "") : (result?.image?.url || "");
            sessionMeta = result?.session || null;
            break;
          }
          if (status === "FAILURE") {
            const backendError = ((st.data as any)?.error || "").toString().trim();
            const msg = backendError || (mode === "music-chat" ? t("chat.error_music_generation") : t("chat.error_image_generation"));
            setMessages((prev) => [...prev, { role: "assistant", content: msg, variant: "error" }]);
            return;
          }
          await delay(1500);
        }

        if (!finalUrl) {
          const msg = mode === "music-chat"
            ? `${t("chat.error_music_generation")} (timeout 10m)`
            : t("chat.error_image_generation");
          setMessages((prev) => [...prev, { role: "assistant", content: msg, variant: "error" }]);
          return;
        }
        setMessages((prev) => [...prev, {
          role: "assistant",
          content: finalUrl,
          attachments: [{ type: mode === "music-chat" ? "audio" : "image", url: finalUrl }],
        }]);

        // Update route if a new session created
        const routeSessionId = sessionMeta?.uid || sessionMeta?.id;
        if (!chatId && sessionMeta && routeSessionId) {
          try {
            if (typeof window !== 'undefined') sessionStorage.setItem(`chat.animate.${routeSessionId}`, '1');
            router.push(`/dashboard/${mode}/${routeSessionId}`);
          } catch {}
          try { window.dispatchEvent(new CustomEvent("chat:session-created", { detail: { id: routeSessionId, uid: sessionMeta.uid, title: sessionMeta.title || content.slice(0, 60), chat_mode: mode } })); } catch {}
        }
      } else {
        const res = await fetchData("ai/chat/", "POST", payload, true);
        setInput("");
        if (!res?.ok) {
          setMessages((prev) => [...prev, { role: "assistant", content: formatError(res), variant: "error" }]);
          return;
        }
        const sessionMeta = (res?.data?.session ?? null) as { id?: string; uid?: string; title?: string } | null;
        const assistantContent = (res?.data as any)?.response || "";
        if (!assistantContent) {
          const msg = t("chat.error_generic");
          setMessages((prev) => [...prev, { role: "assistant", content: msg, variant: "error" }]);
        } else {
          setMessages((prev) => [...prev, { role: "assistant", content: assistantContent }]);
        }
        const routeSessionId = sessionMeta?.uid || sessionMeta?.id;
        if (!chatId && sessionMeta && routeSessionId) {
          try {
            if (typeof window !== 'undefined') sessionStorage.setItem(`chat.animate.${routeSessionId}`, '1');
            router.push(`/dashboard/${mode}/${routeSessionId}`);
          } catch {}
          try { window.dispatchEvent(new CustomEvent("chat:session-created", { detail: { id: routeSessionId, uid: sessionMeta.uid, title: sessionMeta.title || content.slice(0, 60), chat_mode: mode } })); } catch {}
        }
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
        mode={mode}
        input={input}
        setInput={setInput}
        handleSubmit={handleSubmit}
        messages={messages}
        setMessages={setMessages}
        attachments={attachments}
        setAttachments={setAttachments}
        musicLanguage={musicLanguage}
        setMusicLanguage={setMusicLanguage}
        musicGenre={musicGenre}
        setMusicGenre={setMusicGenre}
        musicTrackType={musicTrackType}
        setMusicTrackType={setMusicTrackType}
      />
    </div>
  );
}
