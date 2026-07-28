"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import Cookies from "js-cookie";
import { FiMenu, FiPlus, FiZap } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import { streamChat } from "@/tools/streamChat";
import { getGuestId } from "@/lib/guest";
import { isJwtValid } from "@/tools/jwt";
import type { Message, ChatSource } from "@/types/chat";
import type { AiModel } from "./ModelSelector";
import ChatMessages from "./ChatMessages";
import ChatComposer from "./ChatComposer";
import StartScreen from "./StartScreen";
import ChatSidebar, { type ChatItem } from "./ChatSidebar";
import EsaiLogo from "@/components/brand/EsaiLogo";
import TopUpModal from "./TopUpModal";
import GuestLimitModal from "./GuestLimitModal";
import PaywallModal, { type PaywallContext, type PaywallReason } from "./PaywallModal";
import { useBalance } from "@/hooks/useBalance";

type Props = {
  /** existing session id when opened from /dashboard/text-chat/<id> */
  chatId?: string;
  /** chat mode kept for routing parity with the dashboard */
  mode?: string;
  /**
   * Контент, который рисуется СРАЗУ ПОД шапкой чата (меню/лого/баланс) и НАД
   * стартовым экраном — используется главной страницей для HomeHero (клиент
   * попросил шапку чата первым элементом на экране, Hero сразу под ней, см.
   * app/(home)/page.tsx). Показывается только на стартовом экране: как
   * только пользователь начинает переписку, чат занимает всю высоту вьюпорта
   * (см. style ниже) — держать там ещё и Hero было бы тесно/лишне.
   */
  heroSlot?: ReactNode;
  /**
   * Контент между композером и баннером «Создание мультфильмов» на стартовом
   * экране — главная страница передаёт сюда WhyEsAI (клиент попросил: сразу
   * после чата «Почему EsAI», потом уже мультфильмы, см. StartScreen.tsx и
   * app/(home)/page.tsx).
   */
  belowComposerSlot?: ReactNode;
  /**
   * Чипы готовых промптов на стартовом экране (см. StartScreen.tsx) — ТОЛЬКО
   * на /dashboard/text-chat (клиент явно попросил их НЕ показывать на
   * главной, см. ClientDashboard.tsx).
   */
  showQuickPrompts?: boolean;
};

const MODE = "text-chat";

/** error_code values that map to the branded up-sell (PaywallModal). */
const PAYWALL_CODES: PaywallReason[] = [
  "premium_locked",
  "insufficient_balance",
  "insufficient_tokens",
  "daily_limit_reached",
];

/**
 * ChatWorkspace — the full EsAI chat experience used by both `/` and the
 * dashboard. First screen is the chat itself (start screen → conversation).
 */
export default function ChatWorkspace({ chatId, mode = MODE, heroSlot, belowComposerSlot, showQuickPrompts }: Props) {
  const router = useRouter();
  const { t, i18n } = useTranslation("common");

  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [attachments, setAttachments] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [model, setModel] = useState("");
  // Активная сессия: из пропа (URL /dashboard/text-chat/<id>) ИЛИ созданная
  // первым сообщением на стартовом «/». КРИТично: после создания сессии держим
  // её id здесь и шлём в chat_id, иначе каждое сообщение = новая сессия и чат
  // «не помнит» предыдущее (и файлы из истории не учитываются).
  const [sessionId, setSessionId] = useState<string | undefined>(chatId);
  useEffect(() => { setSessionId(chatId); }, [chatId]);
  // Поддерживает ли выбранная модель изображения (vision). undefined — ещё не
  // известно (не блокируем). Нужно, чтобы не отправлять картинку в текстовую
  // модель (иначе провайдер вернёт ошибку «no image input»).
  const [modelVision, setModelVision] = useState<boolean | undefined>(undefined);
  // Видео-модель (category === "video"): к ней можно прикрепить ФОТО как первый
  // кадр (image-to-video), несмотря на supports_vision=false — не блокируем.
  const [modelIsVideo, setModelIsVideo] = useState(false);
  // Модель генерации изображений (category==="image", напр. FLUX/Nano Banana): к
  // ней МОЖНО прикрепить фото — для FLUX это редактирование (замена фона/объектов),
  // несмотря на supports_vision=false. Не блокируем прикрепление.
  const [modelIsImageEdit, setModelIsImageEdit] = useState(false);
  // Высота вьюпорта с учётом клавиатуры (мобайл): держим контейнер равным
  // visualViewport.height, чтобы при открытии клавиатуры layout СЖИМАЛСЯ и поле
  // ввода/контент оставались в видимой зоне, а не уезжали под клавиатуру.
  const [viewportH, setViewportH] = useState<string>("100dvh");
  // Открыта ли экранная клавиатура (мобайл): вьюпорт заметно ниже окна. Нужно,
  // чтобы на стартовом экране прижать контент к верху (без пустого провала под
  // композером), а в обычном состоянии — центрировать.
  const [keyboardOpen, setKeyboardOpen] = useState(false);
  useEffect(() => {
    const vv = typeof window !== "undefined" ? window.visualViewport : null;
    if (!vv) return;
    const apply = () => {
      setViewportH(`${Math.round(vv.height)}px`);
      setKeyboardOpen(vv.height < window.innerHeight * 0.8);
    };
    apply();
    vv.addEventListener("resize", apply);
    vv.addEventListener("scroll", apply);
    return () => {
      vv.removeEventListener("resize", apply);
      vv.removeEventListener("scroll", apply);
    };
  }, []);
  const [animateIndex, setAnimateIndex] = useState<number | null>(null);
  const [webSearch, setWebSearch] = useState(false);
  // Растёт при программной подстановке промпта (быстрые действия, каталог
  // задач) — сигнал для ChatComposer поставить фокус и курсор в конец текста.
  const [focusSignal, setFocusSignal] = useState(0);

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [topUpOpen, setTopUpOpen] = useState(false);
  /** non-null shows the branded up-sell modal (premium/insufficient/daily). */
  const [paywall, setPaywall] = useState<PaywallContext | null>(null);
  const [guestLimitOpen, setGuestLimitOpen] = useState(false);
  /** Remaining free guest messages, shown until the user signs in. null = unknown. */
  const [guestFree, setGuestFree] = useState<{ used: number; limit: number } | null>(null);
  const [chats, setChats] = useState<ChatItem[]>([]);

  const { balance, setBalance, refresh: refreshBalance } = useBalance();
  const lastUserRef = useRef<string>("");

  // Авторизован ли пользователь. Гостю вместо баланса «0» показываем кнопку
  // «Войти» (в шапке и в меню) — вход сразу на виду, ноль не пугает. Считаем
  // после монтирования (cookie доступен только на клиенте).
  const [isAuthed, setIsAuthed] = useState(false);
  useEffect(() => { setIsAuthed(isJwtValid(Cookies.get("access"))); }, []);

  const started = messages.length > 0;

  /**
   * Routes a refusal (from the SSE error frame OR the JSON fallback) to the
   * right modal. `data` carries `error_code` and any extra fields the backend
   * attached (min_package_kgs, balance_tokens, required_estimate, limit).
   * Returns true when it consumed the error so the caller can skip the generic
   * error bubble. `guest` lets us still honour the legacy guest-limit shape.
   */
  const handleErrorCode = useCallback(
    (data: any, opts?: { authed?: boolean }): boolean => {
      const code: string | undefined =
        data?.error_code || (typeof data?.error === "string" ? data.error : undefined);

      // Guest exhausted free quota -> sign-in modal (ТЗ 3.1).
      if (code === "guest_limit_reached" || (opts?.authed === false && code === "unauthorized")) {
        setGuestLimitOpen(true);
        return true;
      }

      if (code && (PAYWALL_CODES as string[]).includes(code)) {
        setPaywall({
          reason: code as PaywallReason,
          minPackageKgs:
            typeof data?.min_package_kgs === "number" ? data.min_package_kgs : undefined,
          balanceTokens:
            typeof data?.balance_tokens === "number" ? data.balance_tokens : undefined,
          requiredEstimate:
            typeof data?.required_estimate === "number" ? data.required_estimate : undefined,
          limit: typeof data?.limit === "number" ? data.limit : undefined,
        });
        return true;
      }
      return false;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  /* ---------- deep-link from SEO pages: /?model=<openrouter_id>&q=<prompt> ---------- */
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const sp = new URLSearchParams(window.location.search);
      const qModel = sp.get("model");
      const qPrompt = sp.get("q");
      let changed = false;
      if (qModel) {
        setModel(qModel);
        // ModelSelector initialises its selection from this key, so keep it in sync.
        try { localStorage.setItem("esai-model", qModel); } catch {}
        changed = true;
      }
      if (qPrompt) {
        setInput(qPrompt);
        changed = true;
      }
      // Clean the URL so a refresh/share doesn't re-trigger the prefill.
      if (changed) {
        const clean = window.location.pathname + window.location.hash;
        window.history.replaceState({}, "", clean);
      }
    } catch {}
    // run once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ---------- load sessions list (только для авторизованных) ---------- */
  useEffect(() => {
    // У гостя истории/сессий нет — НЕ дёргаем авторизованный эндпоинт, иначе
    // в консоли сыплется 401 (Unauthorized) на /api/ai/sessions/.
    if (!isJwtValid(Cookies.get("access"))) {
      setChats([]);
      return;
    }
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

  // Идёт ли загрузка истории существующего чата. Пока true — показываем спиннер,
  // а НЕ стартовый экран: иначе при открытии/переключении чата на медленном
  // интернете мелькала «главная», пока подгружалась история (жалоба клиента).
  const [hydrating, setHydrating] = useState<boolean>(!!chatId);

  /* ---------- hydrate history for an existing session ---------- */
  useEffect(() => {
    let ignore = false;
    if (!chatId) {
      setMessages([]);
      setHydrating(false);
      return;
    }
    // Сразу показываем загрузку нового чата (без стартового экрана и без старой
    // истории от предыдущего чата).
    setHydrating(true);
    setMessages([]);
    (async () => {
      try {
        const res = await fetchData<any>(`ai/sessions/${chatId}/`, "GET", null, true);
        if (ignore) return;
        const history = (res?.data?.messages || res?.data?.results?.messages) as Message[] | undefined;
        if (Array.isArray(history)) setMessages(history);
      } catch {
        if (!ignore) setMessages([]);
      } finally {
        if (!ignore) setHydrating(false);
      }
    })();
    return () => { ignore = true; };
  }, [chatId]);

  /* ---------- guest chat: persist transcript + migrate into account on login ---------- */
  // Гостевой чат в БД не пишется. Держим транскрипт в localStorage и после
  // логина импортируем его в аккаунт (эндпоинт ai/sessions/import/).
  useEffect(() => {
    try {
      if (isJwtValid(Cookies.get("access"))) return; // только гость
      const real = messages.filter(
        (m) =>
          (m.role === "user" || m.role === "assistant") &&
          (m.content || "").trim() &&
          (m as any).variant !== "error" &&
          !(m as any).streaming
      );
      if (real.length >= 2) {
        localStorage.setItem(
          "esai-guest-pending",
          JSON.stringify(real.slice(-60).map((m) => ({ role: m.role, content: m.content, attachments: (m as any).attachments || null })))
        );
      }
    } catch {}
  }, [messages]);

  useEffect(() => {
    if (chatId) return; // открыт конкретный чат — не трогаем
    if (!isJwtValid(Cookies.get("access"))) return;
    let pending: any[] = [];
    try { pending = JSON.parse(localStorage.getItem("esai-guest-pending") || "[]"); } catch {}
    if (!Array.isArray(pending) || pending.length < 2) return;
    let on = true;
    (async () => {
      const res = await fetchData<any>("ai/sessions/import/", "POST", { messages: pending }, true);
      const s = (res?.data as any)?.session;
      if (!on) return;
      if (res.ok && s?.uid) {
        try { localStorage.removeItem("esai-guest-pending"); } catch {}
        setMessages(pending.map((m: any) => ({ role: m.role, content: m.content, attachments: m.attachments || undefined })) as Message[]);
        setSessionId(s.uid);
        try { window.dispatchEvent(new CustomEvent("chat:session-created", { detail: { id: s.uid, uid: s.uid, title: s.title, chat_mode: mode } })); } catch {}
      }
    })();
    return () => { on = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
        const payload: any = { message: content, templates, mode, model, stream: true };
        if (webSearch) payload.web_search = true;
        if (sessionId) payload.chat_id = sessionId;
        if (readyAttachments.length) payload.attachments = readyAttachments;
        if (i18n?.language) payload.lang = i18n.language;

        // Authenticated users go through the Bearer path. Guests send X-Guest-Id
        // and must NOT trigger the auth redirect, so guest errors are handled here.
        const authed = isJwtValid(Cookies.get("access"));
        const extraHeaders = authed ? undefined : { "X-Guest-Id": getGuestId() };

        // Append a live (empty) assistant bubble we'll fill from the stream.
        // No typing-effect animation: real deltas drive the text now.
        setAnimateIndex(null);
        let assistantIndex = -1;
        setMessages((prev) => {
          assistantIndex = prev.length;
          return [...prev, { role: "assistant", content: "", streaming: true } as Message];
        });

        // Helper: patch the live assistant message by index.
        const patchAssistant = (patch: Partial<Message>, appendDelta?: string, appendReasoning?: string) => {
          setMessages((prev) => {
            const out = [...prev];
            const i = assistantIndex >= 0 && assistantIndex < out.length ? assistantIndex : out.length - 1;
            const cur = out[i];
            if (!cur || cur.role !== "assistant") return prev;
            const curReasoning = ((cur.meta as any)?.reasoning as string) || "";
            // meta: при стриме reasoning — дописываем; при patch.meta (done) —
            // сохраняем уже накопленный reasoning, если бэк его не прислал.
            const meta =
              appendReasoning != null
                ? { ...(cur.meta || {}), reasoning: curReasoning + appendReasoning }
                : patch.meta !== undefined
                ? { ...(curReasoning ? { reasoning: curReasoning } : {}), ...patch.meta }
                : cur.meta;
            out[i] = {
              ...cur,
              ...patch,
              content: appendDelta != null ? (cur.content || "") + appendDelta : (patch.content ?? cur.content),
              meta,
            };
            return out;
          });
        };

        // Drop the empty live bubble (used on stream/JSON errors so we can append an error bubble).
        const dropLiveBubble = () => {
          setMessages((prev) => {
            const out = [...prev];
            const i = assistantIndex >= 0 && assistantIndex < out.length ? assistantIndex : out.length - 1;
            if (out[i]?.role === "assistant" && out[i]?.streaming && !(out[i]?.content || "").trim()) {
              out.splice(i, 1);
            }
            return out;
          });
        };

        let streamErrored = false;
        let sawDelta = false;
        // done тоже успех: image-модели НЕ шлют текстовых дельт (картинка и
        // caption приходят одним done) — без этого флага после успешной
        // генерации картинки появлялся ложный пузырь «Произошла ошибка».
        let sawDone = false;

        const result = await streamChat(payload, {
          authed,
          extraHeaders,
          onEvent: (ev) => {
            if (ev.type === "delta") {
              sawDelta = true;
              patchAssistant({ streaming: true }, ev.delta);
            } else if (ev.type === "reasoning") {
              // «Мысли» reasoning-модели (DeepSeek R1) — копим отдельно от ответа.
              patchAssistant({ streaming: true }, undefined, ev.delta);
            } else if (ev.type === "sources") {
              const clean = (ev.sources || []).filter((s) => s && s.url) as ChatSource[];
              if (clean.length) patchAssistant({ sources: clean });
            } else if (ev.type === "image_pending") {
              // Готовится картинка (image-gen / авто-роутинг «нарисуй…») —
              // пузырь ассистента показывает серый плейсхолдер как в ChatGPT.
              patchAssistant({ streaming: true, imagePending: true } as any);
            } else if (ev.type === "video_pending") {
              // Готовится видео (video-gen) — пузырь ассистента показывает
              // видео-плейсхолдер («Видео создаётся… обычно 1–2 минуты»).
              patchAssistant({ streaming: true, videoPending: true } as any);
            } else if (ev.type === "video_progress") {
              // keepalive-кадр (~каждые 5с) во время генерации видео — ничего не делаем.
            } else if (ev.type === "error") {
              streamErrored = true;
              dropLiveBubble();
              // SSE error frame: route premium/insufficient/daily/guest to a modal;
              // fall back to an inline error bubble for everything else.
              const frame = { ...(ev.payload || {}), error_code: ev.error_code, error: ev.error };
              const consumed = handleErrorCode(frame, { authed });
              if (!consumed) {
                setMessages((prev) => [...prev, { role: "assistant", content: ev.error, variant: "error" } as any]);
              }
            } else if (ev.type === "done") {
              sawDone = true;
              const p = ev.payload || {};
              // Finalize message metadata (id from server, etc.)
              const finalContent = typeof p?.message?.content === "string" ? p.message.content : undefined;
              const finalId = p?.message?.id;
              // Сохраняем метрику токенов в сообщение, чтобы показать под ответом
              // «сколько списано» (требование клиента). tokens_charged = списанные
              // кредиты (с учётом коэф. модели); total_tokens — сырьё провайдера.
              const usageMeta = (p?.message?.meta || {}) as Record<string, any>;
              const chargedTok =
                // ТОЛЬКО реально списанные кредиты. Раньше был фолбэк на total_tokens —
                // у гостей (кредиты не списываются) подпись показывала сырые ТОКЕНЫ
                // («90 кредитов» за «123») и пугала. Нет tokens_charged → нет подписи.
                typeof p.tokens_charged === "number" ? p.tokens_charged : undefined;
              // Вложения ассистента (сгенерированные картинки image-gen моделей):
              // бэк сохраняет их на сообщении, done.message их уже несёт.
              const finalAtts = Array.isArray(p?.message?.attachments) && p.message.attachments.length
                ? p.message.attachments
                : undefined;
              patchAssistant({
                streaming: false,
                imagePending: false,
                videoPending: false,
                ...(finalContent != null ? { content: finalContent } : {}),
                ...(finalId != null ? { id: finalId } : {}),
                ...(finalAtts ? ({ attachments: finalAtts } as any) : {}),
                meta: { ...usageMeta, tokens_charged: chargedTok },
              } as any);
              if (typeof p.balance_tokens === "number") setBalance(Math.max(0, p.balance_tokens));
              else if (authed) refreshBalance();
              if (typeof p.free_limit === "number") {
                setGuestFree({ used: Number(p.free_used) || 0, limit: Number(p.free_limit) || 0 });
              }
              const sessionMeta = (p.session ?? p?.message?.session ?? null) as { id?: string; uid?: string; title?: string } | null;
              const routeId = sessionMeta?.uid || sessionMeta?.id;
              if (!sessionId && sessionMeta && routeId) {
                // Привязываем созданную сессию → следующие сообщения идут в неё
                // (чат помнит контекст и учитывает ранее загруженные файлы).
                setSessionId(routeId);
                try { window.dispatchEvent(new CustomEvent("chat:session-created", { detail: { id: routeId, uid: sessionMeta.uid, title: sessionMeta.title || content.slice(0, 60), chat_mode: mode } })); } catch {}
              }
            }
          },
        });

        /* ---------- non-stream fallback (402/401-before-stream or plain JSON) ---------- */
        if (!result.isStream) {
          dropLiveBubble();
          const data = (result.json as any) || {};

          // Route any known refusal (error_code) to the matching modal.
          if (handleErrorCode(data, { authed })) return;

          // Legacy / status-only fallbacks (older backend without error_code).
          if (!authed && result.status === 401) {
            setGuestLimitOpen(true);
            return;
          }
          if (result.status === 402) {
            setPaywall({ reason: "insufficient_tokens" });
            return;
          }
          if (!result.ok) {
            const msg = (data?.detail || data?.error || t("chat.error_request_failed", { defaultValue: "Запрос не выполнен." })).toString();
            setMessages((prev) => [...prev, { role: "assistant", content: msg, variant: "error" } as any]);
            return;
          }

          const assistantContent = data.response || "";
          if (typeof data.balance_tokens === "number") setBalance(Math.max(0, data.balance_tokens));
          else if (authed) refreshBalance();
          if (data.guest && typeof data.free_limit === "number") {
            setGuestFree({ used: Number(data.free_used) || 0, limit: Number(data.free_limit) || 0 });
          }

          if (!assistantContent) {
            setMessages((prev) => [...prev, { role: "assistant", content: t("chat.error_generic", { defaultValue: "Произошла ошибка." }), variant: "error" } as any]);
          } else {
            const srcs = Array.isArray(data.sources) ? (data.sources.filter((s: any) => s && s.url) as ChatSource[]) : undefined;
            setMessages((prev) => {
              const next = [...prev, { role: "assistant", content: assistantContent, sources: srcs } as Message];
              setAnimateIndex(next.length - 1); // keep the typing-effect for the non-stream path
              return next;
            });
          }

          const sessionMeta = (data.session ?? null) as { id?: string; uid?: string; title?: string } | null;
          const routeId = sessionMeta?.uid || sessionMeta?.id;
          if (!sessionId && sessionMeta && routeId) {
            setSessionId(routeId);
            try { window.dispatchEvent(new CustomEvent("chat:session-created", { detail: { id: routeId, uid: sessionMeta.uid, title: sessionMeta.title || content.slice(0, 60), chat_mode: mode } })); } catch {}
          }
          return;
        }

        /* ---------- post-stream cleanup ---------- */
        if (streamErrored) {
          // Error already surfaced and the live bubble dropped; nothing to finalize.
        } else if (!sawDelta && !sawDone) {
          dropLiveBubble();
          setMessages((prev) => [...prev, { role: "assistant", content: t("chat.error_generic", { defaultValue: "Произошла ошибка." }), variant: "error" } as any]);
        } else {
          // Ensure the bubble isn't left in a streaming state if `done` never arrived.
          patchAssistant({ streaming: false });
        }
      } catch (e) {
        console.error("chat request failed", e);
        // Remove any leftover empty live bubble before showing the network error.
        setMessages((prev) => {
          const out = [...prev];
          const last = out[out.length - 1];
          if (last?.role === "assistant" && last?.streaming && !(last.content || "").trim()) out.pop();
          return [...out, { role: "assistant", content: t("chat.error_network", { defaultValue: "Сетевая ошибка." }), variant: "error" } as any];
        });
      } finally {
        setLoading(false);
      }
    },
    [attachments, sessionId, i18n.language, mode, model, webSearch, refreshBalance, setBalance, t, handleErrorCode]
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
      // Новый чат на стартовом «/»: сбрасываем активную сессию, иначе следующее
      // сообщение прилепится к предыдущему диалогу.
      setSessionId(undefined);
      setMessages([]);
      setInput("");
      setAttachments([]);
    }
  };

  // Композер чата (поле ввода) — единый узел: на старте он рендерится в герое
  // сразу под слоганом (виден без прокрутки), в диалоге — снизу. Под полем —
  // счётчик бесплатных сообщений гостя.
  const composerNode = (
    <>
      <ChatComposer
        input={input}
        setInput={setInput}
        onSubmit={handleSubmit}
        disabled={loading}
        attachments={attachments}
        setAttachments={setAttachments}
        model={model}
        onModelChange={(id, m) => { setModel(id); setModelVision(m?.supports_vision); setModelIsVideo((m?.category || "") === "video"); setModelIsImageEdit((m?.category || "") === "image"); }}
        autoFocus={!started}
        focusSignal={focusSignal}
        webSearch={webSearch}
        onToggleWebSearch={setWebSearch}
        menuDirection={started ? "up" : "down"}
        modelSupportsVision={modelVision}
        modelIsVideo={modelIsVideo}
        modelIsImageEdit={modelIsImageEdit}
      />
      {guestFree && guestFree.limit > 0 && (
        <p className="text-center text-xs text-muted-2 mt-2">
          {t("guest.free_remaining", {
            defaultValue: "Осталось {{count}} из {{limit}} бесплатных сообщений",
            count: Math.max(0, guestFree.limit - guestFree.used),
            limit: guestFree.limit,
          })}
        </p>
      )}
    </>
  );

  // На /dashboard/text-chat (heroSlot не передают — см. ClientDashboard.tsx)
  // держим чат на полную высоту экрана ВСЕГДА, даже до первого сообщения —
  // это воссоздаёт эффект «две страницы в одной» (просьба клиента,
  // 24.07.2026 вечером): статья+футер полностью под первым экраном, их
  // открывает только осознанный скролл вниз. На главной (heroSlot есть —
  // Hero уже занимает верх экрана) это НЕ нужно и раньше давало пустой
  // чёрный провал под коротким контентом — там высота остаётся
  // content-driven (min-h вместо жёсткого height).
  const forceFullHeight = started || hydrating || !heroSlot;

  return (
    <div
      className={
        "flex flex-col bg-background text-foreground" +
        (forceFullHeight ? "" : " min-h-[60vh] sm:min-h-[70vh]")
      }
      style={forceFullHeight ? { height: viewportH } : undefined}
    >
      {/* Top bar. pt = safe-area-inset-top: в установленном PWA (statusBarStyle
          black-translucent) контент рисуется ПОД системной строкой iOS — без
          этого отступа лого/баланс налезали на время и зарядку. Высота = ряд
          + вырез, ряд остаётся 3.5rem и центрируется ниже статус-бара. */}
      <header className="flex items-center justify-between px-3 sm:px-4 h-[calc(3.5rem_+_env(safe-area-inset-top,0px))] pt-[env(safe-area-inset-top,0px)] border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            className="w-10 h-10 grid place-items-center rounded-lg text-muted hover:text-foreground hover:bg-surface-2 cursor-pointer"
            title={t("chat.menu", { defaultValue: "Меню" })}
          >
            <FiMenu className="text-xl" />
          </button>
          <a href="/" className="flex items-center gap-2">
            <EsaiLogo className="h-6 w-auto" />
          </a>
        </div>
        <div className="flex items-center gap-2">
          {isAuthed ? (
            <button
              type="button"
              onClick={() => setTopUpOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 hover:border-accent/60 text-sm px-3 py-2 cursor-pointer"
              title={t("balance.topup", { defaultValue: "Пополнить" })}
            >
              <FiZap className="text-accent" />
              <span className="font-medium">{(balance ?? 0).toLocaleString()}</span>
            </button>
          ) : (
            // Гость: вместо баланса «0» — заметная кнопка «Войти».
            <a
              href="/auth/signin"
              className="inline-flex items-center rounded-full bg-accent text-on-accent text-sm font-semibold px-4 py-2 hover:bg-accent-strong transition-colors"
            >
              {t("auth.login", { defaultValue: "Войти" })}
            </a>
          )}
          <button
            type="button"
            onClick={newChat}
            className="w-10 h-10 grid place-items-center rounded-lg text-muted hover:text-foreground hover:bg-surface-2 cursor-pointer"
            title={t("chat.new_chat", { defaultValue: "Новый чат" })}
          >
            <FiPlus className="text-xl" />
          </button>
        </div>
      </header>

      {!started && !hydrating && heroSlot}

      {/* Body */}
      <main className="flex-1 min-h-0 flex flex-col px-3 sm:px-4">
        {started ? (
          <>
            <ChatMessages
              messages={messages}
              loading={loading}
              animateIndex={animateIndex}
              onRetry={handleRetry}
              onContinue={handleContinue}
              onFeedback={handleFeedback}
            />
            {/* Composer внизу в режиме диалога */}
            <div className="pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2 shrink-0">{composerNode}</div>
          </>
        ) : hydrating ? (
          // Загрузка истории открываемого чата — спиннер вместо стартового экрана
          // (иначе на медленном интернете мелькала «главная»).
          <div className="flex-1 grid place-items-center">
            <span className="inline-block w-8 h-8 rounded-full border-2 border-border border-t-accent animate-spin" />
          </div>
        ) : (
          // Стартовый экран: композер сразу под слоганом (виден без прокрутки),
          // быстрые действия и сценарии — ниже (ТЗ клиента: «чат вверх»).
          <StartScreen
            onUsePrompt={(text) => { setInput(text); setFocusSignal((n) => n + 1); }}
            composerSlot={composerNode}
            belowComposerSlot={belowComposerSlot}
            showQuickPrompts={showQuickPrompts}
            keyboardOpen={keyboardOpen}
          />
        )}
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
      <PaywallModal
        context={paywall}
        onClose={() => setPaywall(null)}
        onTopUp={() => setTopUpOpen(true)}
      />
      <GuestLimitModal open={guestLimitOpen} onClose={() => setGuestLimitOpen(false)} />
    </div>
  );
}
