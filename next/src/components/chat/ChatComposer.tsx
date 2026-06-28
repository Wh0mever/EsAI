"use client";

import React, { useEffect, useRef, type FormEvent, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { IoIosSend, IoIosAttach } from "react-icons/io";
import { IoDocumentTextOutline, IoGlobeOutline } from "react-icons/io5";
import { FiFileText } from "react-icons/fi";
import { fetchData, BACKEND } from "@/tools/fetchData";
import ModelSelector, { type AiModel } from "./ModelSelector";

/** Accepted document types for the RAG document picker (ТЗ 2.12). */
const DOC_ACCEPT =
  ".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt," +
  "application/pdf," +
  "application/msword," +
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document," +
  "application/vnd.ms-excel," +
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet," +
  "application/vnd.ms-powerpoint," +
  "application/vnd.openxmlformats-officedocument.presentationml.presentation," +
  "text/plain";

type Props = {
  input: string;
  setInput: (v: string) => void;
  onSubmit: (e: FormEvent) => void;
  disabled?: boolean;
  attachments: any[];
  setAttachments: React.Dispatch<React.SetStateAction<any[]>>;
  model: string;
  onModelChange: (id: string, m: AiModel) => void;
  autoFocus?: boolean;
  webSearch?: boolean;
  onToggleWebSearch?: (v: boolean) => void;
};

/**
 * ChatComposer — the input bar: textarea + model selector + attach + send.
 * Handles auto-grow, Enter-to-send, file uploads and keeps itself visible when
 * the mobile keyboard appears (Visual Viewport API).
 */
export default function ChatComposer({
  input,
  setInput,
  onSubmit,
  disabled,
  attachments,
  setAttachments,
  model,
  onModelChange,
  autoFocus,
  webSearch = false,
  onToggleWebSearch,
}: Props) {
  const { t } = useTranslation("common");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const docInputRef = useRef<HTMLInputElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const autoGrow = () => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
    }
  };
  useEffect(autoGrow, [input]);

  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus();
  }, [autoFocus]);

  // Keep composer pinned above the on-screen keyboard on mobile.
  useEffect(() => {
    const vv = typeof window !== "undefined" ? window.visualViewport : null;
    if (!vv) return;
    const onResize = () => {
      const overlap = Math.max(0, window.innerHeight - (vv.height + vv.offsetTop));
      if (wrapRef.current) wrapRef.current.style.transform = overlap > 0 ? `translateY(-${overlap}px)` : "";
    };
    vv.addEventListener("resize", onResize);
    vv.addEventListener("scroll", onResize);
    return () => {
      vv.removeEventListener("resize", onResize);
      vv.removeEventListener("scroll", onResize);
    };
  }, []);

  const uploading = Array.isArray(attachments) && attachments.some((a: any) => a?.status === "uploading");
  const hasDocument =
    Array.isArray(attachments) &&
    attachments.some((a: any) => a?.type === "document" || a?.type === "file");

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (uploading) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSubmit(e as any);
    }
  };

  /**
   * Shared upload routine for both the media picker and the document picker.
   * `kind` only decides the placeholder type of the pending chip — the server
   * response (which carries the authoritative `type`, e.g. "document", plus
   * `url`, `name`, `text`) overwrites it once parsing finishes.
   */
  const uploadFiles = async (files: File[], kind: "media" | "document") => {
    if (!files.length) return;
    const pending = files.map((f) => ({
      name: f.name,
      type: kind === "document" ? "document" : f.type?.startsWith("image/") ? "image" : "file",
      preview: kind === "media" ? URL.createObjectURL(f) : undefined,
      status: "uploading",
    }));
    setAttachments((prev) => [...prev, ...pending]);
    try {
      const fd = new FormData();
      for (const f of files) fd.append("files", f);
      const res = await fetchData<{ attachments: any[] }>("ai/attachments/upload/", "POST", fd, true);
      const list = (res?.data as any)?.attachments;
      if (!res?.ok || !Array.isArray(list) || list.length === 0) {
        setAttachments((prev) => {
          const out = [...prev];
          for (let i = out.length - pending.length; i < out.length; i++) if (i >= 0) out[i] = { ...out[i], status: "error" };
          return out;
        });
      } else {
        setAttachments((prev) => {
          const out = [...prev];
          for (let i = out.length - pending.length, j = 0; i < out.length && j < list.length; i++, j++) {
            try { if (out[i]?.preview) URL.revokeObjectURL(out[i].preview); } catch {}
            out[i] = { ...list[j], status: "ready" };
          }
          return out;
        });
      }
    } catch {
      setAttachments((prev) => {
        const out = [...prev];
        for (let i = out.length - pending.length; i < out.length; i++) if (i >= 0) out[i] = { ...out[i], status: "error" };
        return out;
      });
    }
  };

  const onFilesPicked = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    try {
      await uploadFiles(files, "media");
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const onDocsPicked = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    try {
      await uploadFiles(files, "document");
    } finally {
      if (docInputRef.current) docInputRef.current.value = "";
    }
  };

  return (
    <div ref={wrapRef} className="w-full max-w-3xl mx-auto transition-transform duration-150">
      {/* Attachments preview */}
      {Array.isArray(attachments) && attachments.length > 0 && (
        <div className="mb-2 flex gap-2 flex-wrap">
          {attachments.map((a, idx) => {
            const isImg = a?.type === "image";
            const raw = a?.url || a?.preview || "";
            const abs = raw && raw.startsWith("/") ? `${BACKEND}${raw}` : raw;
            return (
              <div key={idx} className="relative shrink-0">
                <button
                  type="button"
                  className="absolute -top-2 -right-2 z-10 bg-rose-600 text-white rounded-full w-5 h-5 text-xs grid place-items-center cursor-pointer"
                  onClick={() => setAttachments((prev) => prev.filter((_, i) => i !== idx))}
                  title={t("common.cancel", { defaultValue: "Удалить" })}
                >
                  ×
                </button>
                {isImg ? (
                  <img src={abs} alt={a?.name || "attachment"} className="w-16 h-16 object-cover rounded-lg border border-border" />
                ) : (
                  <div
                    className="h-16 max-w-[12rem] bg-surface-2 rounded-lg flex items-center gap-2 px-3 text-foreground border border-border"
                    title={a?.name || "document"}
                  >
                    <IoDocumentTextOutline className="text-xl shrink-0 text-accent-strong" />
                    <span className="flex flex-col min-w-0">
                      <span className="truncate text-xs font-medium max-w-[8rem]">{a?.name || "document"}</span>
                      <span className="text-[10px] text-muted-2">
                        {a?.status === "uploading"
                          ? t("chat.doc_parsing", { defaultValue: "Обработка…" })
                          : a?.status === "error"
                          ? t("chat.doc_error", { defaultValue: "Ошибка" })
                          : t("chat.doc_ready", { defaultValue: "Документ" })}
                      </span>
                    </span>
                  </div>
                )}
                {a?.status === "uploading" && (
                  <div className="absolute inset-0 bg-black/40 grid place-items-center text-[10px] text-white rounded-lg">
                    {t("status.loading", { defaultValue: "..." })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <form
        onSubmit={onSubmit}
        className="bg-surface border border-border rounded-3xl px-3 py-2.5 shadow-lg focus-within:border-accent/60 transition-colors"
      >
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onInput={autoGrow}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder={
            hasDocument
              ? t("chat.ask_about_document", { defaultValue: "Задайте вопрос по документу" })
              : t("chat.ask_something", { defaultValue: "Спросите что-нибудь..." })
          }
          className="w-full resize-none overflow-y-auto bg-transparent outline-none text-foreground placeholder:text-muted-2 px-1 py-1 leading-6 max-h-[200px]"
        />
        <div className="flex items-center justify-between gap-2 mt-1.5">
          <div className="flex items-center gap-1.5">
            <ModelSelector value={model} onChange={onModelChange} />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="w-9 h-9 grid place-items-center rounded-full text-muted hover:text-foreground hover:bg-surface-2 transition-colors cursor-pointer"
              title={t("chat.attachments", { defaultValue: "Вложения" })}
            >
              <IoIosAttach className="text-xl" />
            </button>
            <input ref={fileInputRef} type="file" multiple className="hidden" onChange={onFilesPicked} />
            <button
              type="button"
              onClick={() => docInputRef.current?.click()}
              className="w-9 h-9 grid place-items-center rounded-full text-muted hover:text-foreground hover:bg-surface-2 transition-colors cursor-pointer"
              title={t("chat.attach_document", { defaultValue: "Прикрепить документ" })}
            >
              <FiFileText className="text-xl" />
            </button>
            <input
              ref={docInputRef}
              type="file"
              multiple
              accept={DOC_ACCEPT}
              className="hidden"
              onChange={onDocsPicked}
            />
            {onToggleWebSearch && (
              <button
                type="button"
                onClick={() => onToggleWebSearch(!webSearch)}
                aria-pressed={webSearch}
                className={
                  "inline-flex items-center gap-1.5 h-9 px-3 rounded-full border text-sm transition-colors cursor-pointer " +
                  (webSearch
                    ? "border-accent/60 bg-accent-soft text-accent-strong"
                    : "border-border text-muted hover:text-foreground hover:bg-surface-2")
                }
                title={t("chat.quick.web_search", { defaultValue: "Поиск в интернете" })}
              >
                <IoGlobeOutline className="text-lg" />
                <span className="hidden sm:inline">{t("chat.web_search_short", { defaultValue: "Поиск" })}</span>
              </button>
            )}
          </div>
          <button
            type="submit"
            disabled={disabled || uploading || !input.trim()}
            className="w-10 h-10 grid place-items-center rounded-full bg-accent text-on-accent hover:bg-accent-strong transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            title={t("chat.send", { defaultValue: "Отправить" })}
          >
            <IoIosSend className="text-xl" />
          </button>
        </div>
      </form>
    </div>
  );
}
