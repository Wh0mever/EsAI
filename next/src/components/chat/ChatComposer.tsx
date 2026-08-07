"use client";

import React, { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { IoIosSend, IoIosAttach } from "react-icons/io";
import { IoDocumentTextOutline, IoGlobeOutline } from "react-icons/io5";
import { FiMic, FiSquare } from "react-icons/fi";
import { fetchData, BACKEND } from "@/tools/fetchData";
import ModelSelector, { type AiModel } from "./ModelSelector";

/**
 * Минимальные типы Web Speech API: их нет в lib.dom для всех таргетов,
 * поэтому объявляем локально ровно то, что используем (голосовой ввод v1,
 * распознавание целиком в браузере, без запросов на бэкенд).
 */
type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: any) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: any) => void) | null;
  start: () => void;
  stop: () => void;
};

/** Конструктор SpeechRecognition с учётом webkit-префикса; null, если API нет. */
const getSpeechRecognitionCtor = (): (new () => SpeechRecognitionLike) | null => {
  if (typeof window === "undefined") return null;
  return (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition || null;
};

/** Язык распознавания из языка интерфейса (i18n). */
const speechLangFor = (uiLang: string | undefined): string => {
  const l = (uiLang || "").toLowerCase();
  if (l.startsWith("en")) return "en-US";
  if (l.startsWith("kg") || l.startsWith("ky")) return "ky-KG";
  return "ru-RU";
};

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
  /**
   * Счётчик: при каждом изменении — фокус в поле + курсор в конец текста.
   * Используется, когда текст подставляется программно (быстрые промпты,
   * каталог задач), не только на монтировании (в отличие от autoFocus).
   */
  focusSignal?: number;
  webSearch?: boolean;
  onToggleWebSearch?: (v: boolean) => void;
  /** Направление меню моделей: "down" на стартовом экране, "up" в диалоге. */
  menuDirection?: "up" | "down";
  /** Поддерживает ли выбранная модель изображения. false → блокируем отправку картинки. */
  modelSupportsVision?: boolean;
  /** Модель генерации картинок (FLUX/Nano Banana): фото разрешено для РЕДАКТИРОВАНИЯ. */
  modelIsImageEdit?: boolean;
  /** Видео-модель (image-to-video): фото разрешено как первый кадр, даже без vision. */
  modelIsVideo?: boolean;
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
  focusSignal,
  webSearch = false,
  onToggleWebSearch,
  menuDirection = "up",
  modelSupportsVision,
  modelIsVideo = false,
  modelIsImageEdit = false,
}: Props) {
  const { t, i18n } = useTranslation("common");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  // --- Голосовой ввод (Web Speech API, целиком в браузере) ---
  // Кнопка микрофона рендерится только там, где API есть (Chrome/Edge/Safari).
  // Feature-detect в useEffect, а не при рендере: компонент "use client", но
  // первый рендер идёт и на сервере, где window нет.
  const [speechSupported, setSpeechSupported] = useState(false);
  const [recording, setRecording] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  // Текст, который был в поле до начала записи, — не затираем его.
  const baseTextRef = useRef("");

  useEffect(() => {
    setSpeechSupported(!!getSpeechRecognitionCtor());
  }, []);

  const stopRecognition = () => {
    const rec = recognitionRef.current;
    recognitionRef.current = null;
    if (rec) {
      rec.onresult = null;
      rec.onend = null;
      rec.onerror = null;
      try { rec.stop(); } catch {}
    }
    setRecording(false);
  };

  const startRecognition = () => {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor || recognitionRef.current) return;
    let rec: SpeechRecognitionLike;
    try {
      rec = new Ctor();
    } catch {
      return;
    }
    rec.lang = speechLangFor(i18n?.language);
    rec.continuous = true;
    rec.interimResults = true;
    baseTextRef.current = input ? input.replace(/\s+$/, "") + " " : "";
    rec.onresult = (event: any) => {
      // При continuous результаты накапливаются: собираем финальные и
      // промежуточные куски из всего списка и показываем их живьём.
      let finalText = "";
      let interimText = "";
      try {
        for (let i = 0; i < event.results.length; i++) {
          const r = event.results[i];
          const chunk = r?.[0]?.transcript || "";
          if (r?.isFinal) finalText += chunk;
          else interimText += chunk;
        }
      } catch {
        return;
      }
      setInput(baseTextRef.current + finalText + interimText);
    };
    rec.onend = () => {
      // Браузер сам останавливает распознавание (тишина/таймаут) — сбрасываем.
      if (recognitionRef.current === rec) {
        recognitionRef.current = null;
        setRecording(false);
      }
    };
    rec.onerror = () => {
      // not-allowed / no-speech / network — тихо выходим из режима записи.
      if (recognitionRef.current === rec) {
        recognitionRef.current = null;
        setRecording(false);
      }
    };
    recognitionRef.current = rec;
    try {
      rec.start();
      setRecording(true);
    } catch {
      recognitionRef.current = null;
      setRecording(false);
    }
  };

  const toggleRecording = () => {
    if (recording) stopRecognition();
    else startRecognition();
  };

  // На размонтировании гасим активное распознавание, чтобы микрофон не висел.
  useEffect(() => {
    return () => {
      const rec = recognitionRef.current;
      recognitionRef.current = null;
      if (rec) {
        rec.onresult = null;
        rec.onend = null;
        rec.onerror = null;
        try { rec.stop(); } catch {}
      }
    };
  }, []);

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

  // Подстановка промпта извне (быстрые действия, каталог задач) — фокус +
  // курсор в конец, чтобы пользователь мог сразу дописать без лишнего клика.
  // Пропускаем самый первый рендер (focusSignal стартует с 0 — не должно
  // конкурировать с autoFocus выше).
  const skipFirstFocusSignal = useRef(true);
  useEffect(() => {
    if (skipFirstFocusSignal.current) {
      skipFirstFocusSignal.current = false;
      return;
    }
    if (focusSignal === undefined) return;
    const el = textareaRef.current;
    if (!el) return;
    el.focus();
    const len = el.value.length;
    el.setSelectionRange(len, len);
  }, [focusSignal]);

  // Возвращаем фокус в поле ввода после ответа ИИ (disabled/loading → false) и
  // при монтировании, чтобы пользователь продолжал печатать, не кликая по чату
  // каждый раз (частая жалоба). Срабатывает только на смене disabled.
  useEffect(() => {
    if (!disabled) textareaRef.current?.focus();
  }, [disabled]);

  // Удержание поля над клавиатурой на мобайле теперь делает родитель
  // (ChatWorkspace) через высоту контейнера = visualViewport.height. Прежний
  // translateY-хак здесь конфликтовал (на стартовом экране поле уезжало за верх).

  const uploading = Array.isArray(attachments) && attachments.some((a: any) => a?.status === "uploading");
  const hasDocument =
    Array.isArray(attachments) &&
    attachments.some((a: any) => a?.type === "document" || a?.type === "file");
  const hasImage =
    Array.isArray(attachments) && attachments.some((a: any) => a?.type === "image");
  // Картинка прикреплена, но выбранная модель без зрения → отправку блокируем
  // (иначе провайдер вернёт ошибку). undefined = ещё не знаем → не блокируем.
  // Видео-модели — исключение: фото для них это первый кадр (image-to-video),
  // поэтому картинку разрешаем, несмотря на supports_vision=false.
  const imageNeedsVision =
    hasImage && modelSupportsVision === false && !modelIsVideo && !modelIsImageEdit;

  // Перед отправкой останавливаем голосовую запись (если шла), затем штатный onSubmit.
  const handleSubmit = (e: FormEvent) => {
    if (recording) stopRecognition();
    onSubmit(e);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (uploading || imageNeedsVision) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as any);
    }
  };

  /**
   * Shared upload routine for both the media picker and the document picker.
   * `kind` only decides the placeholder type of the pending chip — the server
   * response (which carries the authoritative `type`, e.g. "document", plus
   * `url`, `name`, `text`) overwrites it once parsing finishes.
   */
  const uploadFiles = async (files: File[], _kind: "media" | "document" = "media") => {
    if (!files.length) return;
    // Тип чипа определяем ПО ФАЙЛУ: единая скрепка принимает и фото, и документы
    // (отдельная кнопка документов убрана по просьбе клиента). Сервер всё равно
    // отдаёт authoritative type после парсинга.
    const pending = files.map((f) => ({
      name: f.name,
      type: f.type?.startsWith("image/") ? "image" : "document",
      preview: f.type?.startsWith("image/") ? URL.createObjectURL(f) : undefined,
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

  // Вставка из буфера обмена (Ctrl+V): скриншоты (image/*) и файлы, скопированные
  // из проводника, грузим как вложения. Обычный текст вставляется штатно.
  const onPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const dt = e.clipboardData;
    if (!dt) return;
    const collected: File[] = [];
    if (dt.files && dt.files.length) {
      for (const f of Array.from(dt.files)) collected.push(f);
    } else if (dt.items && dt.items.length) {
      for (const it of Array.from(dt.items)) {
        if (it.kind === "file") {
          const f = it.getAsFile();
          if (f) collected.push(f);
        }
      }
    }
    if (!collected.length) return; // обычный текст — штатное поведение
    e.preventDefault();
    const isDoc = (f: File) =>
      /\.(pdf|docx?|xlsx?|pptx?|txt)$/i.test(f.name || "") ||
      /(pdf|msword|wordprocessing|ms-excel|spreadsheet|ms-powerpoint|presentation|text\/plain)/i.test(f.type || "");
    const docs = collected.filter(isDoc);
    const media = collected.filter((f) => !isDoc(f));
    if (media.length) uploadFiles(media, "media");
    if (docs.length) uploadFiles(docs, "document");
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
        onSubmit={handleSubmit}
        className="bg-surface border border-border rounded-3xl px-3 py-2.5 shadow-lg focus-within:border-accent/60 transition-colors"
      >
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onInput={autoGrow}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
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
            <ModelSelector value={model} onChange={onModelChange} menuDirection={menuDirection} />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="w-9 h-9 grid place-items-center rounded-full text-muted hover:text-foreground hover:bg-surface-2 transition-colors cursor-pointer"
              title={t("chat.attachments", { defaultValue: "Вложения" })}
            >
              <IoIosAttach className="text-xl" />
            </button>
            {/* Единственная скрепка: и фото, и документы (кнопку документов убрали —
                просьба клиента; на мобиле ряд кнопок вытеснял «Отправить»). */}
            <input ref={fileInputRef} type="file" multiple className="hidden" onChange={onFilesPicked} />
            {speechSupported && (
              <button
                type="button"
                onClick={toggleRecording}
                aria-pressed={recording}
                className={
                  "w-9 h-9 grid place-items-center rounded-full transition-colors cursor-pointer " +
                  (recording
                    ? "text-rose-500 bg-rose-500/10 animate-pulse"
                    : "text-muted hover:text-foreground hover:bg-surface-2")
                }
                title={
                  recording
                    ? t("chat.voice_stop", { defaultValue: "Остановить запись" })
                    : t("chat.voice_input", { defaultValue: "Голосовой ввод" })
                }
                aria-label={
                  recording
                    ? t("chat.voice_stop", { defaultValue: "Остановить запись" })
                    : t("chat.voice_input", { defaultValue: "Голосовой ввод" })
                }
              >
                {recording ? <FiSquare className="text-lg" /> : <FiMic className="text-lg" />}
              </button>
            )}
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
            disabled={disabled || uploading || imageNeedsVision || !input.trim()}
            className="w-10 h-10 grid place-items-center rounded-full bg-accent text-on-accent hover:bg-accent-strong transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            title={t("chat.send", { defaultValue: "Отправить" })}
          >
            <IoIosSend className="text-xl" />
          </button>
        </div>
      </form>

      {imageNeedsVision && (
        <p className="mt-2 text-center text-xs text-amber-700 dark:text-amber-500">
          {t("chat.image_no_vision", {
            defaultValue:
              "Выбранная модель не понимает изображения. Выберите ChatGPT, Gemini или Claude (с пометкой «Фото»).",
          })}
        </p>
      )}

      {/* Модель картинок (FLUX) + фото: подсказка про редактирование. */}
      {!imageNeedsVision && hasImage && modelIsImageEdit && !modelIsVideo && (
        <p className="mt-2 text-center text-xs text-muted-2">
          {t("chat.image_edit_hint", { defaultValue: "ИИ отредактирует ваше фото по описанию" })}
        </p>
      )}

      {/* Видео-модель + фото: мягкая подсказка (не блокирует отправку).
          Показываем только когда предупреждение о vision НЕ активно. */}
      {!imageNeedsVision && hasImage && modelIsVideo && (
        <p className="mt-2 text-center text-xs text-muted-2">
          {t("chat.image_to_video_hint", { defaultValue: "Фото станет первым кадром видео" })}
        </p>
      )}
    </div>
  );
}
