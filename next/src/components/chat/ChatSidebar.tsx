"use client";

import React, { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import Cookies from "js-cookie";
import {
  FiPlus,
  FiX,
  FiUser,
  FiSettings,
  FiZap,
  FiSun,
  FiMoon,
  FiMonitor,
  FiLogOut,
  FiTrash2,
} from "react-icons/fi";
import NextLink from "@/components/ui/nextLink/NextLink";
import { ConfirmationModal } from "@/components/dialog/Dialog";
import { fetchData } from "@/tools/fetchData";
import { useTheme } from "@/hooks/useTheme";

export type ChatItem = { id: string; uid?: string; title: string; chat_mode?: string };

type Props = {
  open: boolean;
  onClose: () => void;
  chats: ChatItem[];
  activeChatId?: string;
  balance: number | null;
  onTopUp: () => void;
  onNewChat: () => void;
};

/**
 * ChatSidebar — slide-in drawer (mobile + desktop) with conversation history,
 * token balance + top-up, profile, settings, theme switcher and language.
 */
export default function ChatSidebar({
  open,
  onClose,
  chats,
  activeChatId,
  balance,
  onTopUp,
  onNewChat,
}: Props) {
  const { t, i18n } = useTranslation("common");
  const { preference, setPreference } = useTheme();
  const [logoutOpen, setLogoutOpen] = useState(false);
  const [clearOpen, setClearOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const isAuthed = typeof window !== "undefined" ? Boolean(Cookies.get("access")) : false;

  // Lock body scroll while drawer open.
  useEffect(() => {
    if (typeof document === "undefined") return;
    document.body.classList.toggle("overflow-hidden", open);
    return () => document.body.classList.remove("overflow-hidden");
  }, [open]);

  const ref = (c: ChatItem) => String(c.uid || c.id);

  const handleLogout = () => {
    Cookies.remove("access");
    Cookies.remove("refresh");
    Cookies.remove("user");
    Cookies.remove("sessionid");
    window.location.href = "/auth/signin";
  };

  const handleClearHistory = async () => {
    if (clearing) return;
    try {
      setClearing(true);
      await fetchData("ai/chat/history/", "DELETE", {}, true);
      try { window.dispatchEvent(new CustomEvent("chat:history-cleared")); } catch {}
      window.location.reload();
    } catch {
      /* noop */
    } finally {
      setClearing(false);
      setClearOpen(false);
    }
  };

  const setLang = (code: "ru" | "en" | "kg") => {
    import("@/lib/locale").then((m) => m.setLanguagePreference(code));
  };

  const themeOptions: { key: "light" | "dark" | "system"; icon: React.ReactNode; label: string }[] = [
    { key: "light", icon: <FiSun />, label: t("theme.light", { defaultValue: "Светлая" }) },
    { key: "dark", icon: <FiMoon />, label: t("theme.dark", { defaultValue: "Тёмная" }) },
    { key: "system", icon: <FiMonitor />, label: t("theme.system", { defaultValue: "Системная" }) },
  ];

  return (
    <>
      <AnimatePresence>
        {open && (
          <>
            <motion.div
              key="backdrop"
              className="fixed inset-0 z-[900]"
              style={{ background: "var(--overlay)" }}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              onClick={onClose}
            />
            <motion.aside
              key="drawer"
              className="fixed inset-y-0 left-0 z-[901] w-[86%] max-w-[320px] bg-surface border-r border-border flex flex-col"
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ type: "tween", duration: 0.28, ease: "easeOut" }}
            >
              {/* Header */}
              <div className="flex items-center justify-between px-3 py-3 border-b border-border shrink-0">
                <img src="/esai-logo.svg" alt="EsAI" className="h-7" />
                <button
                  type="button"
                  onClick={onClose}
                  className="p-2 rounded-lg hover:bg-surface-2 text-muted hover:text-foreground cursor-pointer"
                  title={t("common.close", { defaultValue: "Закрыть" })}
                >
                  <FiX />
                </button>
              </div>

              {/* New chat */}
              <div className="px-3 pt-3 shrink-0">
                <button
                  type="button"
                  onClick={() => {
                    onNewChat();
                    onClose();
                  }}
                  className="w-full inline-flex items-center gap-2 rounded-xl border border-border bg-surface-2 hover:border-accent/60 text-foreground text-sm px-3 py-2.5 transition-colors cursor-pointer"
                >
                  <FiPlus className="text-accent" />
                  {t("chat.new_chat", { defaultValue: "Новый чат" })}
                </button>
              </div>

              {/* History */}
              <div className="px-3 pt-4 flex-1 min-h-0 flex flex-col">
                <div className="text-[11px] uppercase tracking-wide text-muted-2 px-1 mb-1">
                  {t("chat.chat_history", { defaultValue: "История чатов" })}
                </div>
                <div className="overflow-y-auto pr-1 flex-1">
                  {chats.length === 0 ? (
                    <div className="text-sm text-muted-2 italic px-1 py-2">
                      {t("chat.chats_list_empty", { defaultValue: "История пуста" })}
                    </div>
                  ) : (
                    <ul className="space-y-1">
                      {chats.map((c) => (
                        <li key={ref(c)}>
                          <NextLink
                            href={`/dashboard/${c.chat_mode || "text-chat"}/${ref(c)}`}
                            onClick={onClose}
                            className={`block rounded-lg px-2.5 py-2 text-sm truncate ${
                              ref(c) === String(activeChatId || "") ? "bg-accent-soft" : "hover:bg-surface-2"
                            }`}
                          >
                            {c.title}
                          </NextLink>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>

              {/* Balance + top up */}
              <div className="px-3 pt-3 shrink-0">
                <div className="rounded-xl border border-border bg-surface-2 p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted">{t("balance.label", { defaultValue: "Баланс токенов" })}</span>
                    <FiZap className="text-accent" />
                  </div>
                  <div className="mt-0.5 text-xl font-bold text-foreground">
                    {balance == null ? "—" : balance.toLocaleString()}
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      onTopUp();
                      onClose();
                    }}
                    className="mt-2 w-full rounded-lg bg-accent text-on-accent font-semibold text-sm py-2 hover:bg-accent-strong transition-colors cursor-pointer"
                  >
                    {t("balance.topup", { defaultValue: "Пополнить" })}
                  </button>
                </div>
              </div>

              {/* Theme switcher */}
              <div className="px-3 pt-3 shrink-0">
                <div className="text-[11px] uppercase tracking-wide text-muted-2 px-1 mb-1">
                  {t("theme.title", { defaultValue: "Тема" })}
                </div>
                <div className="grid grid-cols-3 gap-1.5">
                  {themeOptions.map((opt) => (
                    <button
                      key={opt.key}
                      type="button"
                      onClick={() => setPreference(opt.key)}
                      className={`flex flex-col items-center gap-1 rounded-lg border py-2 text-xs transition-colors cursor-pointer ${
                        preference === opt.key
                          ? "border-accent bg-accent-soft text-foreground"
                          : "border-border hover:bg-surface-2 text-muted"
                      }`}
                    >
                      <span className="text-base">{opt.icon}</span>
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Language */}
              <div className="px-3 pt-3 shrink-0">
                <div className="text-[11px] uppercase tracking-wide text-muted-2 px-1 mb-1">
                  {t("common.language", { defaultValue: "Язык" })}
                </div>
                <div className="flex gap-1.5">
                  {(["ru", "en", "kg"] as const).map((code) => (
                    <button
                      key={code}
                      type="button"
                      onClick={() => setLang(code)}
                      className={`flex-1 rounded-lg border py-1.5 text-sm transition-colors cursor-pointer ${
                        i18n.language === code
                          ? "border-accent bg-accent-soft text-foreground"
                          : "border-border hover:bg-surface-2 text-muted"
                      }`}
                    >
                      {code.toUpperCase()}
                    </button>
                  ))}
                </div>
              </div>

              {/* Footer actions */}
              <div className="px-3 py-3 mt-2 border-t border-border shrink-0 space-y-1">
                <NextLink
                  href="/profile"
                  onClick={onClose}
                  className="flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2 cursor-pointer"
                >
                  <FiUser className="text-muted" /> {t("chat.profile", { defaultValue: "Профиль" })}
                </NextLink>
                <NextLink
                  href="/pricing"
                  onClick={onClose}
                  className="flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2 cursor-pointer"
                >
                  <FiSettings className="text-muted" /> {t("common.settings", { defaultValue: "Настройки" })}
                </NextLink>
                {isAuthed && (
                  <>
                    <button
                      type="button"
                      onClick={() => setClearOpen(true)}
                      className="w-full flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2 cursor-pointer text-left"
                    >
                      <FiTrash2 className="text-muted" /> {t("chat.clear_history", { defaultValue: "Очистить историю" })}
                    </button>
                    <button
                      type="button"
                      onClick={() => setLogoutOpen(true)}
                      className="w-full flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2 cursor-pointer text-left text-rose-400"
                    >
                      <FiLogOut /> {t("nav.logout", { defaultValue: "Выйти" })}
                    </button>
                  </>
                )}
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      <ConfirmationModal
        isOpen={logoutOpen}
        title={t("nav.logOutConfirmTitle", { defaultValue: "Выйти из аккаунта?" })}
        confirmText={t("common.yes", { defaultValue: "Да" })}
        cancelText={t("common.no", { defaultValue: "Нет" })}
        onConfirm={handleLogout}
        onCancel={() => setLogoutOpen(false)}
      />
      <ConfirmationModal
        isOpen={clearOpen}
        title={t("chat.clear_history_confirm_title", { defaultValue: "Очистить историю?" })}
        description={t("chat.clear_history_confirm_desc", { defaultValue: "Действие необратимо." })}
        confirmText={t("common.yes", { defaultValue: "Да" })}
        confirmLoadingText={t("common.loading", { defaultValue: "Загрузка..." })}
        cancelText={t("common.no", { defaultValue: "Нет" })}
        onConfirm={handleClearHistory}
        onCancel={() => setClearOpen(false)}
        confirmDisabled={clearing}
      />
    </>
  );
}
