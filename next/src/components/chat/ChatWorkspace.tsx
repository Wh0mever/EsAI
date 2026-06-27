"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { FiMenu, FiPlus, FiZap } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import type { Message } from "@/types/chat";
import type { AiModel } from "./ModelSelector";
import ChatMessages from "./ChatMessages";
import ChatComposer from "./ChatComposer";
import StartScreen from "./StartScreen";
import ChatSidebar, { type ChatItem } from "./ChatSidebar";
import TopUpModal from "./TopUpModal";
import InsufficientTokensModal from "./InsufficientTokensModal";
import { useBalance } from "@/hooks/useBalance";

type Props = {
  /** existing session id when opened from /dashboard/text-chat/<id> */
  chatId?: string;
  /** chat mode kept for routing parity with the dashboard */
  mode?: string;
};

const MODE = "text-chat";

/**
 * ChatWorkspace — the full EsAI chat experience used by both `/` and the
 * dashboard. First screen is the chat itself (start screen → conversation).
 */
export default function ChatWorkspace({ chatId, mode = MODE }: Props) {
  const router = useRouter();
  const { t, i18n } = useTranslation("common");

  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [attachments, setAttachments] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [model, setModel] = useState("");
  const [animateIndex, setAnimateIndex] = useState<number | null>(null);

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [topUpOpen, setTopUpOpen] = useState(false);
  const [insufficientOpen, setInsufficientOpen] = useState(false);
  const [chats, setChats] = useState<ChatItem[]>([]);

  const { balance, setBalance, refresh: refreshBalance } = useBalance();
  const lastUserRef = useRef<string>("");

  const started = messages.length > 0;

  /* ---------- load sessions list ---------- */
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const res = await fetchData<ChatItem[]>("ai/sessions/", "GET", null, true);
        if (mounted) setChats(Array.isArray(res?.data) ? res.data : []);
      } catch {
        if (mounted) setChats([]);
      }
    })();
    return () => { mounted = false; };
  }, []);

  // keep sidebar in sync when a session is created elsewhere
  useEffect(() => {
    const onCreated = (e: any) => {
      const d = e?.detail;
      if (!d?.id) return;
      setChats((prev) => {
        const exists = prev.some((c) => String(c.uid || c.id) === String(d.uid || d.id));
        if (exists) return prev;
        return [{ id: d.id, uid: d.uid || d.id, title: d.title || "New Chat", chat_mode: d.chat_mode || mode }, ...prev];
      });
    };
    window.addEventListener("chat:session-created", onCreated as any);
    return () => window.removeEventListener("chat:session-created", onCreated as any);
  }, [mode]);

  /* ---------- hydrate history for an existing session ---------- */
  useEffect(() => {
    let ignore = false;
    if (!chatId) {
      setMessages([]);
      return;
    }
    (async () => {
      try {
        const res = await fetchData<any>(`ai/sessions/${chatId}/`, "GET", null, true);
        if (ignore) return;
        const history = (res?.data?.messages || res?.data?.results?.messages) as Message[] | undefined;
        if (Array.isArray(history)) setMessages(history);
      } catch {
        if (!ignore) setMessages([]);
      }
    })();
    return () => { ignore = true; };
  }, [chatId]);

  /* ---------- send ---------- */
  const sendMessage = useCallback(
    async (raw: string, opts?: { append?: boolean }) => {
      const content = raw.trim();
      if (!content) return;
      if (attachments.some((a) => a?.status === "uploading")) return;

      const readyAttachments = attachments.filter((a) => a && a.url);
      lastUserRef.current = content;

      if (!opts?.append) {
        setMessages((prev) => [
          ...prev,
          { role: "user", content, attachments: readyAttachments.length ? [...readyAttachments] : undefined },
        ]);
      }
      setInput("");
      setAttachments([]);

      try {
        setLoading(true);
        const templates = (() => { try { return localStorage.getItem("ai-templates"); } catch { return null; } })();
        const payload: any = { message: content, templates, mode, model };
        if (chatId) payload.chat_id = chatId;
        if (readyAttachments.length) payload.attachments = readyAttachments;
        if (i18n?.language) payload.lang = i18n.language;

        const res = await fetchData<any>("ai/chat/", "POST", payload, true);

        // Insufficient tokens
        if (res?.status === 402 || (res?.data as any)?.error === "insufficient_tokens") {
          setInsufficientOpen(true);
          return;
        }
        if (!res?.ok) {
          const msg = (res?.error || (res?.data as any)?.error || t("chat.error_request_failed", { defaultValue: "Запрос не выполнен." })).toString();
          setMessages((prev) => [...prev, { role: "assistant", content: msg, variant: "error" } as any]);
          return;
        }

        const data = res.data || {};
        const assistantContent = data.response || "";
        // update balance from response if present
        if (typeof data.balance_tokens === "number") setBalance(data.balance_tokens);
        else refreshBalance();

        if (!assistantContent) {
          setMessages((prev) => [...prev, { role: "assistant", content: t("chat.error_generic", { defaultValue: "Произошла ошибка." }), variant: "error" } as any]);
        } else {
          setMessages((prev) => {
            const next = [...prev, { role: "assistant", content: assistantContent } as Message];
            // type out the freshly appended answer
            setAnimateIndex(next.length - 1);
            return next;
          });
        }

        // route to the dashboard session when a new one was created (parity with old flow)
        const sessionMeta = (data.session ?? null) as { id?: string; uid?: string; title?: string } | null;
        const routeId = sessionMeta?.uid || sessionMeta?.id;
        if (!chatId && sessionMeta && routeId) {
          try { window.dispatchEvent(new CustomEvent("chat:session-created", { detail: { id: routeId, uid: sessionMeta.uid, title: sessionMeta.title || content.slice(0, 60), chat_mode: mode } })); } catch {}
        }
      } catch (e) {
        console.error("chat request failed", e);
        setMessages((prev) => [...prev, { role: "assistant", content: t("chat.error_network", { defaultValue: "Сетевая ошибка." }), variant: "error" } as any]);
      } finally {
        setLoading(false);
      }
    },
    [attachments, chatId, i18n.language, mode, model, refreshBalance, setBalance, t]
  );

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    sendMessage(input);
  };

  const handleRetry = useCallback(() => {
    if (!lastUserRef.current) return;
    // drop the last assistant message, then resend the previous user prompt
    setMessages((prev) => {
      const out = [...prev];
      if (out.length && out[out.length - 1].role === "assistant") out.pop();
      return out;
    });
    sendMessage(lastUserRef.current, { append: true });
  }, [sendMessage]);

  const handleContinue = useCallback(() => {
    sendMessage(t("chat.actions.continue_prompt", { defaultValue: "Продолжи." }), { append: true });
  }, [sendMessage, t]);

  const handleFeedback = useCallback((index: number, value: "up" | "down") => {
    const msg = messages[index] as any;
    const id = msg?.id;
    if (id == null) return;
    fetchData("ai/chat/feedback/", "POST", { message_id: id, value }, true).catch(() => {});
  }, [messages]);

  const newChat = () => {
    if (chatId) {
      router.push("/");
    } else {
      setMessages([]);
      setInput("");
      setAttachments([]);
    }
  };

  return (
    <div className="flex flex-col h-[100dvh] bg-background text-foreground">
      {/* Top bar */}
      <header className="flex items-center justify-between px-3 sm:px-4 h-14 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            className="w-9 h-9 grid place-items-center rounded-lg text-muted hover:text-foreground hover:bg-surface-2 cursor-pointer"
            title={t("chat.menu", { defaultValue: "Меню" })}
          >
            <FiMenu className="text-xl" />
          </button>
          <a href="/" className="flex items-center gap-2">
            <img src="/esai-logo.svg" alt="EsAI" className="h-6" />
          </a>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setTopUpOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 hover:border-accent/60 text-sm px-3 py-1.5 cursor-pointer"
            title={t("balance.topup", { defaultValue: "Пополнить" })}
          >
            <FiZap className="text-accent" />
            <span className="font-medium">{balance == null ? "—" : balance.toLocaleString()}</span>
          </button>
          <button
            type="button"
            onClick={newChat}
            className="w-9 h-9 grid place-items-center rounded-lg text-muted hover:text-foreground hover:bg-surface-2 cursor-pointer"
            title={t("chat.new_chat", { defaultValue: "Новый чат" })}
          >
            <FiPlus className="text-xl" />
          </button>
        </div>
      </header>

      {/* Body */}
      <main className="flex-1 min-h-0 flex flex-col px-3 sm:px-4">
        {started ? (
          <ChatMessages
            messages={messages}
            loading={loading}
            animateIndex={animateIndex}
            onRetry={handleRetry}
            onContinue={handleContinue}
            onFeedback={handleFeedback}
          />
        ) : (
          <StartScreen onUsePrompt={(text) => setInput(text)} />
        )}

        {/* Composer */}
        <div className="pb-3 pt-2 shrink-0">
          <ChatComposer
            input={input}
            setInput={setInput}
            onSubmit={handleSubmit}
            disabled={loading}
            attachments={attachments}
            setAttachments={setAttachments}
            model={model}
            onModelChange={(id) => setModel(id)}
            autoFocus={!started}
          />
          {!started && (
            <p className="text-center text-xs text-muted-2 mt-2">
              {t("brand.slogan", { defaultValue: "Все AI в одном месте." })}
            </p>
          )}
        </div>
      </main>

      {/* Drawer + modals */}
      <ChatSidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        chats={chats}
        activeChatId={chatId}
        balance={balance}
        onTopUp={() => setTopUpOpen(true)}
        onNewChat={newChat}
      />
      <TopUpModal open={topUpOpen} onClose={() => setTopUpOpen(false)} />
      <InsufficientTokensModal
        open={insufficientOpen}
        onClose={() => setInsufficientOpen(false)}
        onTopUp={() => setTopUpOpen(true)}
      />
    </div>
  );
}
