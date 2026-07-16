"use client";

import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { FiDownload, FiLoader } from "react-icons/fi";
import { useTranslation } from "react-i18next";
import Markdown from "./Markdown";
import MessageActions from "./MessageActions";
import NextLink from "@/components/ui/nextLink/NextLink";
import { BACKEND } from "@/tools/fetchData";
import { saveMedia, prefetchMedia } from "@/tools/saveMedia";
import type { Message, ChatSource } from "@/types/chat";

function toAbsUrl(raw?: string): string {
  if (!raw) return "";
  return raw.startsWith("/") ? `${BACKEND}${raw}` : raw;
}

/* ---------- typing effect (streaming-ready) ---------- */
function useTyping(text: string, enabled: boolean, onTick: () => void) {
  const [count, setCount] = useState(enabled ? 0 : text.length);
  const doneRef = useRef(!enabled);

  useEffect(() => {
    if (!enabled) {
      setCount(text.length);
      doneRef.current = true;
      return;
    }
    setCount(0);
    doneRef.current = false;
    let i = 0;
    // chunk a few chars per tick so long answers don't crawl
    const step = Math.max(1, Math.round(text.length / 600));
    const id = window.setInterval(() => {
      i = Math.min(i + step, text.length);
      setCount(i);
      onTick();
      if (i >= text.length) {
        doneRef.current = true;
        window.clearInterval(id);
      }
    }, 16);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, enabled]);

  return { shown: text.slice(0, count), done: doneRef.current || count >= text.length };
}

// Индикатор «Думаю…» (как у конкурентов): иконка-мозг + мерцающий текст, висит
// до прихода ответа и исчезает, как только пошёл стрим. Реального reasoning у
// большинства моделей нет — это UI-плейсхолдер ожидания.
function ThinkingDots() {
  const { t } = useTranslation("common");
  return (
    <span className="inline-flex items-center gap-2 text-sm text-muted" aria-live="polite">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="size-4 shrink-0 animate-pulse"
        aria-hidden="true"
      >
        <path d="M12 18V5" />
        <path d="M15 13a4.17 4.17 0 0 1-3-4 4.17 4.17 0 0 1-3 4" />
        <path d="M17.598 6.5A3 3 0 1 0 12 5a3 3 0 1 0-5.598 1.5" />
        <path d="M17.997 5.125a4 4 0 0 1 2.526 5.77" />
        <path d="M18 18a4 4 0 0 0 2-7.464" />
        <path d="M19.967 17.483A4 4 0 1 1 12 18a4 4 0 1 1-7.967-.517" />
        <path d="M6 18a4 4 0 0 1-2-7.464" />
        <path d="M6.003 5.125a4 4 0 0 0-2.526 5.77" />
      </svg>
      <span className="esai-shimmer">{t("chat.thinking", { defaultValue: "Думаю…" })}</span>
    </span>
  );
}

/**
 * SaveMediaButton — кнопка «Скачать» с мгновенной реакцией и защитой от дабл-тапа.
 * Пока saveMedia качает файл (видео — секунды), кнопка ЗАБЛОКИРОВАНА и показывает
 * спиннер: иначе пользователь тыкал ещё раз-другой, думая что «не жмётся», и потом
 * шитшет «Куда сохранить» выскакивал несколько раз подряд (жалоба клиента).
 */
function SaveMediaButton({
  url,
  filename,
  className,
  iconClassName,
  label,
  children,
}: {
  url: string;
  filename: string;
  className?: string;
  iconClassName?: string;
  label?: string;
  children?: React.ReactNode;
}) {
  const [saving, setSaving] = useState(false);
  return (
    <button
      type="button"
      disabled={saving}
      aria-busy={saving}
      aria-label={label}
      title={label}
      // Предзагрузка на нажатие пальцем/мышью — к моменту click файл уже готов,
      // и на iOS navigator.share() успевает в окно «user activation» (иначе на
      // тяжёлом видео шитшет отклонялся и открывался битый предпросмотр).
      onPointerDown={() => prefetchMedia(url)}
      onClick={(e) => {
        e.stopPropagation();
        if (saving) return;
        setSaving(true);
        // finally в saveMedia + локальный флаг снимают состояние по завершении
        // (в т.ч. когда пользователь закрыл нативный шитшет).
        void saveMedia(url, filename).finally(() => setSaving(false));
      }}
      className={`${className || ""} disabled:opacity-70 disabled:cursor-wait`}
    >
      {saving ? (
        <FiLoader className={`${iconClassName || ""} animate-spin`} />
      ) : (
        <FiDownload className={iconClassName} />
      )}
      {children}
    </button>
  );
}

/**
 * ImageLightbox — просмотр картинки ПОВЕРХ чата (портал в body, z выше сайдбара).
 * Раньше картинка была голой ссылкой <a target="_blank">: в установленном PWA
 * (standalone, без адресной строки и «назад») она открывалась внутри приложения
 * без пути обратно — приходилось перезапускать приложение (жалоба клиента).
 * Закрытие: ✕, тап по фону, Escape.
 */
function ImageLightbox({ url, alt, onClose }: { url: string; alt: string; onClose: () => void }) {
  const { t } = useTranslation("common");
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    document.body.classList.add("overflow-hidden");
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.classList.remove("overflow-hidden");
    };
  }, [onClose]);
  if (typeof document === "undefined") return null;
  return createPortal(
    <div
      className="fixed inset-0 z-[1200] bg-black/90 flex items-center justify-center p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={alt}
    >
      {/* Скачать картинку (просьба клиента). В установленном PWA (iOS) <a download>
          игнорируется — используем saveMedia (Web Share → нативный шитшет). */}
      <SaveMediaButton
        url={url}
        filename={
          (alt || "esai-image").replace(/[^\w.\-]+/g, "_") +
          (url.match(/\.(png|jpe?g|webp)(\?|$)/i) ? "" : ".png")
        }
        label={t("chat.actions.download_image", { defaultValue: "Скачать изображение" })}
        iconClassName="text-xl"
        className="absolute top-4 right-[4.5rem] z-10 w-11 h-11 rounded-full bg-white/10 hover:bg-white/20 text-white grid place-items-center cursor-pointer"
      />
      <button
        type="button"
        onClick={onClose}
        aria-label={t("common.close", { defaultValue: "Закрыть" })}
        className="absolute top-4 right-4 z-10 w-11 h-11 rounded-full bg-white/10 hover:bg-white/20 text-white text-2xl leading-none grid place-items-center cursor-pointer"
      >
        ×
      </button>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={url}
        alt={alt}
        className="max-w-[92vw] max-h-[88vh] object-contain rounded-lg select-none"
        onClick={(e) => e.stopPropagation()}
      />
    </div>,
    document.body
  );
}

function Attachments({ atts }: { atts?: any[] }) {
  const { t } = useTranslation("common");
  const [viewer, setViewer] = useState<{ url: string; alt: string } | null>(null);
  if (!Array.isArray(atts) || atts.length === 0) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-2">
      {atts.map((a, i) => {
        const isImg = (a?.type || "").toLowerCase() === "image";
        const isVideo = (a?.type || "").toLowerCase() === "video";
        const url = toAbsUrl(a?.url || a?.preview || "");
        if (isVideo) {
          // Сгенерированное видео (video-gen модели): плеер + ссылка «Скачать».
          return (
            <div key={i} className="flex flex-col gap-1">
              <video
                controls
                playsInline
                preload="metadata"
                src={url}
                className="w-64 sm:w-80 rounded-xl border border-border"
              />
              <SaveMediaButton
                url={url}
                filename={a?.name || "esai-video.mp4"}
                label={t("chat.actions.download_video", { defaultValue: "Скачать видео" })}
                iconClassName="text-[13px]"
                className="inline-flex items-center gap-1 text-xs text-muted-2 hover:text-foreground transition-colors self-start"
              >
                Скачать видео
              </SaveMediaButton>
            </div>
          );
        }
        return isImg ? (
          <button
            key={i}
            type="button"
            onClick={() => setViewer({ url, alt: a?.name || "attachment" })}
            className="cursor-zoom-in"
            aria-label={a?.name || t("chat.open_image", { defaultValue: "Открыть изображение" })}
          >
            <img src={url} alt={a?.name || "attachment"} className="w-24 h-24 object-cover rounded-lg border border-border" />
          </button>
        ) : (
          <a
            key={i}
            href={url}
            target="_blank"
            rel="noreferrer"
            className="px-3 py-2 text-xs bg-surface-2 hover:bg-surface-3 rounded-lg border border-border inline-flex items-center gap-2"
          >
            <span className="truncate max-w-[8rem]">{a?.name || "file"}</span>
          </a>
        );
      })}
      {viewer && (
        <ImageLightbox url={viewer.url} alt={viewer.alt} onClose={() => setViewer(null)} />
      )}
    </div>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function Sources({ sources }: { sources?: ChatSource[] }) {
  const { t } = useTranslation("common");
  if (!Array.isArray(sources) || sources.length === 0) return null;
  const clean = sources.filter((s) => s && s.url);
  if (clean.length === 0) return null;
  return (
    <div className="mt-2 rounded-xl border border-border bg-surface-2/60 px-3 py-2.5">
      <p className="text-xs font-semibold text-muted mb-1.5">
        {t("chat.sources", { defaultValue: "Источники" })}
      </p>
      <ol className="flex flex-col gap-1">
        {clean.map((s, i) => (
          <li key={`${s.url}-${i}`} className="text-sm leading-snug flex gap-2">
            <span className="text-muted-2 shrink-0 tabular-nums">{i + 1}.</span>
            <a
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent-strong hover:underline underline-offset-2 break-words min-w-0"
              title={s.url}
            >
              <span>{s.title?.trim() || hostOf(s.url)}</span>
              <span className="text-muted-2 text-xs ml-1">({hostOf(s.url)})</span>
            </a>
          </li>
        ))}
      </ol>
    </div>
  );
}

// Раскрываемая «Цепочка размышлений» reasoning-моделей (DeepSeek R1 и т.п.).
// thinking=true — модель ещё «думает» (reasoning стримится, ответа нет):
// показываем мерцающее «Думаю…». Когда пошёл ответ — заголовок сворачивается
// в «Цепочка размышлений» (по клику раскрывается полный ход мыслей).
function ReasoningBlock({ text, thinking }: { text: string; thinking: boolean }) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  if (!text && !thinking) return null;
  return (
    <div className="not-prose w-full mb-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 text-sm text-muted hover:text-foreground transition-colors"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
          className={`size-4 shrink-0 ${thinking ? "animate-pulse" : ""}`} aria-hidden="true"
        >
          <path d="M12 18V5" /><path d="M15 13a4.17 4.17 0 0 1-3-4 4.17 4.17 0 0 1-3 4" />
          <path d="M17.598 6.5A3 3 0 1 0 12 5a3 3 0 1 0-5.598 1.5" /><path d="M17.997 5.125a4 4 0 0 1 2.526 5.77" />
          <path d="M18 18a4 4 0 0 0 2-7.464" /><path d="M19.967 17.483A4 4 0 1 1 12 18a4 4 0 1 1-7.967-.517" />
          <path d="M6 18a4 4 0 0 1-2-7.464" /><path d="M6.003 5.125a4 4 0 0 0-2.526 5.77" />
        </svg>
        <span className={`min-w-0 truncate text-left ${thinking ? "esai-shimmer" : ""}`}>
          {thinking ? t("chat.thinking", { defaultValue: "Думаю…" }) : t("chat.reasoning", { defaultValue: "Цепочка размышлений" })}
        </span>
        {text && (
          <svg
            xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
            className={`size-4 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true"
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        )}
      </button>
      {open && text && (
        <div className="mt-2 rounded-lg border border-border bg-surface-2/50 p-3 text-xs text-muted whitespace-pre-wrap leading-relaxed max-h-72 overflow-y-auto">
          {text}
        </div>
      )}
    </div>
  );
}

function AssistantBubble({
  msg,
  animate,
  onScroll,
  onRetry,
  onContinue,
  onFeedback,
}: {
  msg: Message;
  animate: boolean;
  onScroll: () => void;
  onRetry?: () => void;
  onContinue?: () => void;
  onFeedback?: (v: "up" | "down") => void;
}) {
  const { t } = useTranslation("common");
  const content = msg.content || "";
  const streaming = (msg as any)?.streaming === true;
  // Typing-effect only on the non-stream fallback path. While streaming, real
  // deltas drive the text, so we render `content` directly.
  const { shown, done: typedDone } = useTyping(content, animate && !streaming, onScroll);

  const isError = (msg as any)?.variant === "error";
  const isWarning = (msg as any)?.variant === "warning";
  const link = ((msg as any)?.link || "").toString().trim();
  const linkLabel = ((msg as any)?.linkLabel || "").toString().trim();
  const sources = (msg as any)?.sources as ChatSource[] | undefined;
  const reasoning = (((msg.meta as any)?.reasoning) as string) || "";
  // «думает» = reasoning стримится, а ответа ещё нет.
  const thinking = streaming && !!reasoning && !content.trim();
  // Готовится картинка (image-gen): серый пульсирующий плейсхолдер как в ChatGPT,
  // исчезает когда done приносит attachments (или стрим завершился).
  const hasAtts = Array.isArray((msg as any)?.attachments) && (msg as any).attachments.length > 0;
  const imagePending = (msg as any)?.imagePending === true && streaming && !hasAtts;
  // Готовится видео (video-gen): пульсирующий 16:9-плейсхолдер с подписью,
  // исчезает когда done приносит attachments (или стрим завершился).
  const videoPending = (msg as any)?.videoPending === true && streaming && !hasAtts;

  // Keep the view pinned to the bottom as streamed text grows.
  useEffect(() => {
    if (streaming) onScroll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, streaming]);

  const text = streaming ? content : shown;
  const showCaret = streaming || (!typedDone && animate);
  const finished = !streaming && (typedDone || !animate);

  const tone = isError
    ? "border border-rose-500/40 bg-rose-500/10"
    : isWarning
    ? "border border-amber-500/40 bg-amber-500/10"
    : "bg-bubble-assistant border border-border";

  return (
    <div className="flex flex-col gap-1 max-w-[88%] sm:max-w-[80%] self-start">
      <div className={`px-4 py-3 rounded-2xl rounded-tl-md text-foreground ${tone}`}>
        {isError || isWarning ? (
          <span className="whitespace-pre-wrap">{content}</span>
        ) : (
          <>
            {(reasoning || thinking) && <ReasoningBlock text={reasoning} thinking={thinking} />}
            {streaming && !text && !reasoning && !imagePending && !videoPending ? (
              <ThinkingDots />
            ) : text ? (
              <span className={showCaret ? "esai-caret" : ""}>
                <Markdown content={text} />
              </span>
            ) : null}
            {imagePending && (
              <div
                className="mt-2 w-56 h-56 sm:w-64 sm:h-64 rounded-xl bg-surface-3 border border-border animate-pulse grid place-items-center"
                aria-label={t("chat.image_generating", { defaultValue: "Изображение создаётся" })}
              >
                <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     strokeWidth="1.5" className="text-muted-2 opacity-70" aria-hidden>
                  <rect x="3" y="3" width="18" height="18" rx="3" />
                  <circle cx="9" cy="9" r="2" />
                  <path d="m21 15-3.5-3.5L9 20" />
                </svg>
              </div>
            )}
            {videoPending && (
              <div
                className="mt-2 w-64 sm:w-80 aspect-video rounded-xl bg-surface-3 border border-border animate-pulse flex flex-col items-center justify-center gap-2"
                aria-label={t("chat.video_generating_short", { defaultValue: "Видео создаётся" })}
              >
                {/* иконка-плёнка (film) — по образцу image-скелетона */}
                <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     strokeWidth="1.5" className="text-muted-2 opacity-70" aria-hidden>
                  <rect x="3" y="3" width="18" height="18" rx="3" />
                  <path d="M7 3v18" />
                  <path d="M17 3v18" />
                  <path d="M3 8h4" />
                  <path d="M3 16h4" />
                  <path d="M17 8h4" />
                  <path d="M17 16h4" />
                  <path d="M3 12h18" />
                </svg>
                <span className="text-xs text-muted-2">{t("chat.video_generating", { defaultValue: "Видео создаётся… обычно 1–2 минуты" })}</span>
              </div>
            )}
          </>
        )}
        {link && (
          <div className="mt-2">
            <NextLink href={link} className="text-accent-strong underline underline-offset-2 cursor-pointer">
              {linkLabel || t("chat.go_to_pricing", { defaultValue: "Перейти к тарифам" })}
            </NextLink>
          </div>
        )}
        {!isError && !isWarning && <Sources sources={sources} />}
        {/* Сгенерированные изображения (image-gen модели) — кликабельны в лайтбокс. */}
        {!isError && !isWarning && <Attachments atts={(msg as any)?.attachments} />}
      </div>
      {!isError && !isWarning && finished && content && (
        <div className="flex items-center gap-3 flex-wrap">
          <MessageActions content={content} onRetry={onRetry} onContinue={onContinue} onFeedback={onFeedback} />
          {typeof (msg.meta as any)?.tokens_charged === "number" && (msg.meta as any).tokens_charged > 0 && (() => {
            // Под ⚡ — СПИСАННЫЕ КРЕДИТЫ (= токены × тариф модели ÷ 1000), не токены.
            const n = (msg.meta as any).tokens_charged as number;
            const word = t("chat.credits_unit", { count: n, defaultValue: "кредитов" });
            return (
              <span
                className="inline-flex items-center gap-1 text-xs text-muted-2 tabular-nums select-none"
                title={t("chat.credits_charged_title", { defaultValue: "Списано кредитов за этот ответ (токены × тариф модели ÷ 1000)" })}
              >
                <span className="text-accent">⚡</span>
                {n.toLocaleString()} {word}
              </span>
            );
          })()}
        </div>
      )}
    </div>
  );
}

function UserBubble({ msg }: { msg: Message }) {
  return (
    <div className="flex flex-col gap-1 max-w-[88%] sm:max-w-[80%] self-end items-end">
      <div className="px-4 py-3 rounded-2xl rounded-tr-md bg-bubble-user border border-border text-foreground whitespace-pre-wrap">
        {msg.content}
      </div>
      <Attachments atts={(msg as any)?.attachments} />
    </div>
  );
}

type Props = {
  messages: Message[];
  loading: boolean;
  animateIndex?: number | null;
  onRetry?: () => void;
  onContinue?: () => void;
  onFeedback?: (index: number, v: "up" | "down") => void;
};

export default function ChatMessages({ messages, loading, animateIndex, onRetry, onContinue, onFeedback }: Props) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const stick = useRef(true);

  const scrollToBottom = () => {
    const el = wrapRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  };

  useEffect(() => {
    if (stick.current) scrollToBottom();
  }, [messages.length, loading]);

  const onScroll = () => {
    const el = wrapRef.current;
    if (!el) return;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight <= 80;
  };

  const last = messages[messages.length - 1];
  const showThinking = loading && last?.role === "user";

  return (
    <div ref={wrapRef} onScroll={onScroll} className="flex-1 overflow-y-auto">
      <div className="flex flex-col gap-4 w-full max-w-3xl mx-auto px-1 py-4">
        {messages.map((msg, i) =>
          msg.role === "user" ? (
            <UserBubble key={(msg as any)?.id != null ? `id-${(msg as any).id}` : `u-${i}`} msg={msg} />
          ) : (
            <AssistantBubble
              key={(msg as any)?.id != null ? `id-${(msg as any).id}` : `a-${i}`}
              msg={msg}
              animate={typeof animateIndex === "number" && i === animateIndex}
              onScroll={() => {
                if (stick.current) scrollToBottom();
              }}
              onRetry={i === messages.length - 1 ? onRetry : undefined}
              onContinue={i === messages.length - 1 ? onContinue : undefined}
              onFeedback={(v) => onFeedback?.(i, v)}
            />
          )
        )}
        {showThinking && (
          <div className="px-4 py-3 rounded-2xl rounded-tl-md bg-bubble-assistant border border-border max-w-[80%] self-start">
            <ThinkingDots />
          </div>
        )}
      </div>
    </div>
  );
}
