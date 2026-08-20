"use client";

import React, { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
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
  FiGift,
  FiEdit2,
  FiCheck,
  FiCpu,
  FiBell,
  FiSend,
  FiTag,
  FiFilm,
} from "react-icons/fi";
import Link from "next/link";
import NextLink from "@/components/ui/nextLink/NextLink";
import EsaiLogo from "@/components/brand/EsaiLogo";
import { ConfirmationModal, Modal } from "@/components/dialog/Dialog";
import MemoryModal from "@/components/chat/MemoryModal";
import PromoActivate from "@/components/cabinet/PromoActivate";
import { fetchData } from "@/tools/fetchData";
import { useTheme } from "@/hooks/useTheme";
import { useBonusSettings } from "@/hooks/useBonusSettings";
import { pushSupported, pushPermission, enablePush } from "@/tools/webPush";

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
  const router = useRouter();
  const { preference, setPreference } = useTheme();
  const bonus = useBonusSettings();
  const [clearOpen, setClearOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [promoOpen, setPromoOpen] = useState(false);
  const isAuthed = typeof window !== "undefined" ? Boolean(Cookies.get("access")) : false;

  // Push-уведомления о бонусах. Показываем пункт только если браузер поддерживает
  // Web Push. Разрешение запрашиваем СТРОГО из жеста (клик) — iOS иначе молча
  // отклоняет. Локально держим статус, чтобы кнопка сразу поменяла текст.
  const [pushCan, setPushCan] = useState(false);
  const [pushState, setPushState] = useState<NotificationPermission | "unsupported">("default");
  const [pushBusy, setPushBusy] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    setPushCan(pushSupported());
    setPushState(pushPermission());
  }, []);
  const handleEnablePush = async () => {
    if (pushBusy || pushState === "granted") return;
    setPushBusy(true);
    try {
      const res = await enablePush();
      // Синхронизируем видимый статус с фактическим разрешением браузера.
      setPushState(pushPermission());
      if (res === "denied") {
        try {
          alert(
            t("push.denied", {
              defaultValue:
                "Уведомления отключены в настройках браузера. Включите их для этого сайта.",
            })
          );
        } catch {}
      } else if (res === "error") {
        try {
          alert(t("push.error", { defaultValue: "Не удалось включить уведомления." }));
        } catch {}
      }
    } finally {
      setPushBusy(false);
    }
  };

  // Профиль (аватар + имя) для шапки/футера сайдбара. Аватар приходит из
  // соц-входа (Telegram photo_url / Google picture) через users/profile/.
  const [profile, setProfile] = useState<{ avatar_url?: string; first_name?: string; last_name?: string; email?: string; telegram?: string } | null>(null);
  useEffect(() => {
    if (!isAuthed) return;
    let on = true;
    fetchData<any>("users/profile/", "get", null, true)
      .then((r) => { if (on) setProfile((r?.data as any)?.user || null); })
      .catch(() => {});
    return () => { on = false; };
  }, [isAuthed]);
  const displayName =
    (profile?.first_name || profile?.last_name)
      ? `${profile?.first_name || ""} ${profile?.last_name || ""}`.trim()
      : profile?.telegram
      ? "@" + profile.telegram
      : profile?.email || t("chat.profile", { defaultValue: "Профиль" });

  // Local, mutable copy of the chat list so rename/delete reflect instantly.
  // Kept in sync with the `chats` prop (parent is the source of truth on load).
  const [items, setItems] = useState<ChatItem[]>(chats);
  useEffect(() => setItems(chats), [chats]);

  // Inline rename state.
  const [editingRef, setEditingRef] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [savingRef, setSavingRef] = useState<string | null>(null);
  const editInputRef = useRef<HTMLInputElement | null>(null);

  // Delete confirmation state.
  const [deleteTarget, setDeleteTarget] = useState<ChatItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Lock body scroll while drawer open.
  useEffect(() => {
    if (typeof document === "undefined") return;
    document.body.classList.toggle("overflow-hidden", open);
    return () => document.body.classList.remove("overflow-hidden");
  }, [open]);

  useEffect(() => {
    if (editingRef) editInputRef.current?.focus();
  }, [editingRef]);

  const ref = (c: ChatItem) => String(c.uid || c.id);

  const startRename = (c: ChatItem) => {
    setEditingRef(ref(c));
    setEditTitle(c.title || "");
  };

  const cancelRename = () => {
    setEditingRef(null);
    setEditTitle("");
  };

  const submitRename = async (c: ChatItem) => {
    const id = ref(c);
    const title = editTitle.trim();
    if (!title || title === (c.title || "")) {
      cancelRename();
      return;
    }
    setSavingRef(id);
    try {
      const res = await fetchData(`ai/sessions/${id}/`, "PATCH", { title }, true);
      if (res.ok) {
        setItems((prev) => prev.map((x) => (ref(x) === id ? { ...x, title } : x)));
      }
    } catch {
      /* noop */
    } finally {
      setSavingRef(null);
      cancelRename();
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget || deleting) return;
    const id = ref(deleteTarget);
    const wasActive = id === String(activeChatId || "");
    setDeleting(true);
    try {
      const res = await fetchData(`ai/sessions/${id}/`, "DELETE", null, true);
      if (res.ok) {
        const remaining = items.filter((x) => ref(x) !== id);
        setItems(remaining);
        // Удалили АКТИВНЫЙ чат → ведём на соседний (самый свежий из оставшихся),
        // а не на основной экран; на "/" уходим только если чатов не осталось.
        if (wasActive) {
          const next = remaining[0];
          if (next) {
            onClose();
            router.push(`/dashboard/${next.chat_mode || "text-chat"}/${ref(next)}`);
          } else {
            router.push("/");
          }
        }
      }
    } catch {
      /* noop */
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  };

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
              // Свайп пальцем влево закрывает меню (как тянуть его назад). drag="x"
              // сам ставит touch-action: pan-y → вертикальный скролл списка чатов
              // не ломается. Не закрыли до порога — dragSnapToOrigin вернёт на место.
              drag="x"
              dragConstraints={{ left: 0, right: 0 }}
              dragElastic={{ left: 0.6, right: 0 }}
              dragSnapToOrigin
              onDragEnd={(_e, info) => {
                if (info.offset.x < -70 || info.velocity.x < -500) onClose();
              }}
            >
              {/* Header */}
              {/* pt учитывает вырез iOS (safe-area) в PWA: сайдбар — fixed от
                  верха экрана, без отступа лого налезал на системную строку. */}
              <div className="flex items-center justify-between px-3 pb-3 pt-[calc(0.75rem_+_env(safe-area-inset-top,0px))] border-b border-border shrink-0">
                <EsaiLogo className="h-7 w-auto" />
                <button
                  type="button"
                  onClick={onClose}
                  className="w-10 h-10 grid place-items-center rounded-lg hover:bg-surface-2 text-muted hover:text-foreground cursor-pointer"
                  title={t("common.close", { defaultValue: "Закрыть" })}
                >
                  <FiX />
                </button>
              </div>

              {/* Прокручиваемая середина: новый чат + история + баланс + тема +
                  язык. Раньше каждая секция была shrink-0 и история flex-1 → на
                  невысоких экранах секции налезали друг на друга («История пуста»
                  уходила под карточку баланса). Теперь всё в одном скролле. */}
              <div className="flex-1 min-h-0 overflow-y-auto">
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

              {/* Флагман: «Создание мультфильмов» — заметная ссылка с бейджем NEW.
                  Ведёт в студию-конвейер /studio (от идеи до готового видео). */}
              <div className="px-3 pt-2 shrink-0">
                <Link
                  href="/studio"
                  onClick={onClose}
                  className="w-full inline-flex items-center gap-2.5 rounded-xl border border-accent/40 bg-accent-soft px-3 py-2.5 text-sm font-semibold text-foreground hover:border-accent transition-colors cursor-pointer"
                >
                  <FiFilm className="text-accent shrink-0" />
                  <span className="flex-1 min-w-0 truncate">
                    🎬 {t("chat.studio", { defaultValue: "Создание мультфильмов" })}
                  </span>
                  <span className="shrink-0 rounded-full bg-accent px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-on-accent">
                    {t("common.new_badge", { defaultValue: "NEW" })}
                  </span>
                </Link>
              </div>

              {/* History */}
              <div className="px-3 pt-4">
                <div className="text-[11px] uppercase tracking-wide text-muted-2 px-1 mb-1">
                  {t("chat.chat_history", { defaultValue: "История чатов" })}
                </div>
                <div className="pr-1">
                  {items.length === 0 ? (
                    <div className="text-sm text-muted-2 italic px-1 py-2">
                      {t("chat.chats_list_empty", { defaultValue: "История пуста" })}
                    </div>
                  ) : (
                    <ul className="space-y-1">
                      {items.map((c) => {
                        const id = ref(c);
                        const isActive = id === String(activeChatId || "");
                        const isEditing = editingRef === id;
                        return (
                          <li key={id}>
                            {isEditing ? (
                              <div
                                className={`flex items-center gap-1 rounded-lg px-2 py-1.5 ${
                                  isActive ? "bg-accent-soft" : "bg-surface-2"
                                }`}
                              >
                                <input
                                  ref={editInputRef}
                                  value={editTitle}
                                  onChange={(e) => setEditTitle(e.target.value)}
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter") submitRename(c);
                                    if (e.key === "Escape") cancelRename();
                                  }}
                                  disabled={savingRef === id}
                                  className="flex-1 min-w-0 bg-surface text-foreground text-sm rounded-md px-2 py-1 border border-border outline-none focus:border-accent"
                                  aria-label={t("chat.rename", { defaultValue: "Переименовать" })}
                                />
                                <button
                                  type="button"
                                  onClick={() => submitRename(c)}
                                  disabled={savingRef === id}
                                  className="p-2 min-w-9 min-h-9 rounded-md text-accent hover:bg-surface cursor-pointer disabled:opacity-60"
                                  title={t("common.save", { defaultValue: "Сохранить" })}
                                >
                                  <FiCheck />
                                </button>
                                <button
                                  type="button"
                                  onClick={cancelRename}
                                  disabled={savingRef === id}
                                  className="p-2 min-w-9 min-h-9 rounded-md text-muted hover:text-foreground hover:bg-surface cursor-pointer disabled:opacity-60"
                                  title={t("common.cancel", { defaultValue: "Отмена" })}
                                >
                                  <FiX />
                                </button>
                              </div>
                            ) : (
                              <div
                                className={`group flex items-center rounded-lg pr-1 ${
                                  isActive ? "bg-accent-soft" : "hover:bg-surface-2"
                                }`}
                              >
                                <NextLink
                                  href={`/dashboard/${c.chat_mode || "text-chat"}/${id}`}
                                  onClick={onClose}
                                  className="flex-1 min-w-0 block px-2.5 py-2 text-sm text-foreground truncate"
                                >
                                  {c.title}
                                </NextLink>
                                <div className="flex items-center shrink-0">
                                  <button
                                    type="button"
                                    onClick={() => startRename(c)}
                                    className="p-2 min-w-9 min-h-9 rounded-md text-muted hover:text-foreground hover:bg-surface cursor-pointer"
                                    title={t("chat.rename", { defaultValue: "Переименовать" })}
                                    aria-label={t("chat.rename", { defaultValue: "Переименовать" })}
                                  >
                                    <FiEdit2 className="text-sm" />
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => setDeleteTarget(c)}
                                    className="p-2 min-w-9 min-h-9 rounded-md text-muted hover:text-rose-400 hover:bg-surface cursor-pointer"
                                    title={t("chat.delete", { defaultValue: "Удалить" })}
                                    aria-label={t("chat.delete", { defaultValue: "Удалить" })}
                                  >
                                    <FiTrash2 className="text-sm" />
                                  </button>
                                </div>
                              </div>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  )}
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

              </div>{/* конец прокручиваемой середины */}

              {/* Закреплён вне прокрутки. Авторизован — баланс + «Пополнить».
                  Гость — вместо баланса «0» заметная кнопка «Войти» с намёком на
                  подарок (баланс и пополнение до входа не показываем). */}
              <div className="px-3 pt-3 pb-1 shrink-0">
                {isAuthed ? (
                  <div className="rounded-xl border border-border bg-surface-2 p-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-muted">{t("balance.label", { defaultValue: "Баланс токенов" })}</span>
                      <FiZap className="text-accent" />
                    </div>
                    <div className="mt-0.5 text-xl font-bold text-foreground">
                      {(balance ?? 0).toLocaleString()}
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
                ) : (
                  <div className="rounded-xl border border-accent/40 bg-accent/[0.07] p-3 text-center">
                    <p className="text-sm text-foreground font-medium mb-2.5">
                      🎁 {bonus.loaded
                        ? t("guest.sidebar_bonus", {
                            count: bonus.welcome_bonus,
                            defaultValue: "{{count}} кредитов в подарок за регистрацию",
                          })
                        : t("guest.sidebar_bonus_plain", {
                            defaultValue: "Бонусные кредиты в подарок за регистрацию",
                          })}
                    </p>
                    <NextLink
                      href="/auth/signin"
                      onClick={onClose}
                      className="flex w-full items-center justify-center rounded-lg bg-accent text-on-accent font-bold text-lg text-center py-3 hover:bg-accent-strong transition-colors cursor-pointer"
                    >
                      {t("auth.login", { defaultValue: "Войти" })}
                    </NextLink>
                  </div>
                )}
              </div>

              {/* Footer actions */}
              <div className="px-3 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] border-t border-border shrink-0 space-y-1">
                {/* Профиль и Настройки — только для вошедших (гостю не нужны,
                    могут запутать; вход у гостя вынесен наверх заметной кнопкой). */}
                {isAuthed && (
                  <NextLink
                    href="/profile"
                    onClick={onClose}
                    className="flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2 cursor-pointer"
                  >
                    {profile?.avatar_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={profile.avatar_url} alt="" className="w-7 h-7 rounded-full object-cover shrink-0 border border-border" />
                    ) : (
                      <span className="w-7 h-7 rounded-full bg-surface-2 grid place-items-center shrink-0">
                        <FiUser className="text-muted" />
                      </span>
                    )}
                    <span className="min-w-0 truncate">{displayName}</span>
                  </NextLink>
                )}
                {isAuthed && (
                  <NextLink
                    href="/pricing"
                    onClick={onClose}
                    className="flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2 cursor-pointer"
                  >
                    <FiSettings className="text-muted" /> {t("common.settings", { defaultValue: "Настройки" })}
                  </NextLink>
                )}
                {/* Партнёрство — из чата раньше было недостижимо (жалоба клиента
                    «пользователь сможет найти?»): ссылки были только в
                    маркетинговой шапке и на /pricing. */}
                <NextLink
                  href="/referral"
                  onClick={onClose}
                  className="flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2 cursor-pointer"
                >
                  <FiGift className="text-accent" /> {t("chat.partnership", { defaultValue: "🤝 Партнёрство" })}
                </NextLink>
                {isAuthed ? (
                  <>
                    <NextLink
                      href="/transfer"
                      onClick={onClose}
                      className="flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2 cursor-pointer"
                    >
                      <FiSend className="text-muted" /> {t("chat.transfer_credits", { defaultValue: "💸 Перевести кредиты" })}
                    </NextLink>
                    <button
                      type="button"
                      onClick={() => setPromoOpen(true)}
                      className="w-full flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2 cursor-pointer text-left"
                    >
                      <FiTag className="text-muted" /> {t("chat.promo", { defaultValue: "🎟 Промокод" })}
                    </button>
                    <button
                      type="button"
                      onClick={() => setMemoryOpen(true)}
                      className="w-full flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2 cursor-pointer text-left"
                    >
                      <FiCpu className="text-muted" /> {t("chat.memory", { defaultValue: "Память" })}
                    </button>
                    {pushCan && (
                      <button
                        type="button"
                        onClick={handleEnablePush}
                        disabled={pushBusy || pushState === "granted"}
                        className="w-full flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2 cursor-pointer text-left disabled:cursor-default"
                      >
                        <FiBell className={pushState === "granted" ? "text-accent" : "text-muted"} />{" "}
                        {pushState === "granted"
                          ? t("push.enabled", { defaultValue: "🔔 Уведомления включены" })
                          : t("push.enable", { defaultValue: "🔔 Уведомления о бонусах" })}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => setClearOpen(true)}
                      className="w-full flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2 cursor-pointer text-left"
                    >
                      <FiTrash2 className="text-muted" /> {t("chat.clear_history", { defaultValue: "Очистить историю" })}
                    </button>
                    <button
                      type="button"
                      onClick={handleLogout}
                      className="w-full flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm hover:bg-surface-2 cursor-pointer text-left text-rose-400"
                    >
                      <FiLogOut /> {t("nav.logout", { defaultValue: "Выйти" })}
                    </button>
                  </>
                ) : null /* гостю «Войти» показываем заметной кнопкой выше, дублировать внизу не нужно */}
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>

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
      <ConfirmationModal
        isOpen={Boolean(deleteTarget)}
        title={t("chat.delete_confirm_title", { defaultValue: "Удалить чат?" })}
        description={t("chat.delete_confirm_desc", { defaultValue: "Чат и все его сообщения будут удалены безвозвратно." })}
        confirmText={t("common.yes", { defaultValue: "Да" })}
        confirmLoadingText={t("common.loading", { defaultValue: "Загрузка..." })}
        cancelText={t("common.no", { defaultValue: "Нет" })}
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
        confirmDisabled={deleting}
      />
      <MemoryModal open={memoryOpen} onClose={() => setMemoryOpen(false)} />
      <Modal
        title={t("promo.title", { defaultValue: "Активировать промокод" })}
        open={promoOpen}
        onClose={() => setPromoOpen(false)}
        size="md"
      >
        <PromoActivate bare />
      </Modal>
    </>
  );
}
