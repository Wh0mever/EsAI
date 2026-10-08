"use client";

/**
 * Видеостудия: запасное поле промпта — обычная textarea (§9.5).
 *
 * Показывается, если модуль TipTap не загрузился (сеть, старый браузер, сбой
 * при создании редактора) или его выключили вручную
 * (localStorage["vstudio:editor"]="textarea" — для проверки на телефонах).
 * Теги пишутся текстом «@Image 1»; наружу уходят:
 *  - onPromptText(text) — родитель отправляет prompt_text, теги разбирает сервер;
 *  - onChange(doc) — тот же документ, собранный на клиенте той же грамматикой
 *    (promptDoc.fromText), чтобы счётчик, черновик и цена работали как обычно.
 * Наложение поверх textarea и свой contentEditable не используем — это и есть
 * «самый надёжный» режим. Ничего не обрезается: сверх предела ввод не принимается.
 */
import { useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { trackVs } from "@/lib/vstudio/api";
import { copyTagFor, inputsFromLabels, serverLabels } from "@/lib/vstudio/labels";
import { cpLength, docKey, fromText, renderText, sanitizeDoc } from "@/lib/vstudio/promptDoc";
import { PROMPT_MAX_CHARS } from "@/lib/vstudio/types";
import type { MentionVia, PickerItem, PromptDoc, RefLabels, Uid } from "@/lib/vstudio/types";
import EditorFrame from "./EditorFrame";
import type { VsPromptEditorProps } from "./editorTypes";
// Только модули без TipTap: textarea живёт в основном куске страницы.
import { atBeforeCaret, imageFiles, MOBILE_QUERY } from "./inputHelpers";
import MentionPicker, { type MentionPickerHandle, type PickerAction } from "./MentionPicker";

type AtState = { query: string; from: number; to: number; via: MentionVia };

/** Сколько ждать, пока родитель положит загруженное фото в лоток и у него появится номер. */
const TAG_WAIT_MS = 5000;

function docText(doc: PromptDoc, labels: RefLabels): string {
  return renderText(sanitizeDoc(doc), serverLabels(labels));
}

function parse(text: string, labels: RefLabels): PromptDoc | null {
  try {
    return fromText(text, inputsFromLabels(labels)).doc;
  } catch {
    return null;
  }
}

export default function TextareaFallback(props: VsPromptEditorProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const tx = useCallback(
    (key: string, ru: string, opts?: Record<string, unknown>) => String(t(key, { defaultValue: ru, ...(opts || {}) })),
    [t],
  );
  const propsRef = useRef(props);
  useLayoutEffect(() => {
    propsRef.current = props;
  });
  const maxChars = props.maxChars ?? PROMPT_MAX_CHARS;
  const [text, setText] = useState(() => docText(props.doc, props.labels));
  const textRef = useRef(text);
  const areaRef = useRef<HTMLTextAreaElement | null>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const pickerHandle = useRef<MentionPickerHandle | null>(null);
  const lastEmitted = useRef<PromptDoc | null>(null);
  /**
   * Человек правил текст в textarea. До первой правки родитель отправляет
   * исходный prompt_doc как есть: в тексте нельзя выразить выключенный чип
   * («@Image —»), и пересборка без нужды его бы потеряла.
   */
  const dirty = useRef(false);
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>());
  const [at, setAt] = useState<AtState | null>(null);
  const atRef = useRef<AtState | null>(null);
  const uploadVia = useRef<MentionVia>("at");
  const [notice, setNotice] = useState<string | null>(null);
  const [innerFull, setInnerFull] = useState(false);
  const fullscreen = props.fullscreen ?? innerFull;
  const [mobile, setMobile] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia(MOBILE_QUERY);
    const read = () => setMobile(mq.matches);
    read();
    mq.addEventListener?.("change", read);
    return () => mq.removeEventListener?.("change", read);
  }, []);

  useEffect(() => {
    const pendingTimers = timers.current;
    return () => {
      for (const id of pendingTimers) clearTimeout(id);
      // Уходим (например, TipTap всё-таки загрузился) — родитель снова шлёт prompt_doc.
      if (dirty.current) propsRef.current.onPromptText?.(null);
    };
  }, []);

  const later = useCallback((fn: () => void, ms: number) => {
    const id = setTimeout(() => {
      timers.current.delete(id);
      fn();
    }, ms);
    timers.current.add(id);
  }, []);

  const setFullscreen = useCallback((open: boolean) => {
    propsRef.current.onFullscreenChange?.(open);
    if (propsRef.current.fullscreen === undefined) setInnerFull(open);
  }, []);

  const mention = useCallback((via: MentionVia) => {
    const cb = propsRef.current.onMention;
    if (cb) cb(via);
    else trackVs("vstudio_mention", { via });
  }, []);

  /** Текст → наружу: prompt_text и документ той же грамматикой. */
  const emit = useCallback((value: string) => {
    const p = propsRef.current;
    dirty.current = true;
    p.onPromptText?.(value);
    const doc = parse(value, p.labels || {});
    if (doc) {
      lastEmitted.current = doc;
      p.onChange(doc);
    }
  }, []);

  const applyText = useCallback(
    (value: string, caret?: number) => {
      textRef.current = value;
      setText(value);
      emit(value);
      if (caret != null) {
        requestAnimationFrame(() => areaRef.current?.setSelectionRange(caret, caret));
      }
    },
    [emit],
  );

  // Документ сменился снаружи (Сжать с ИИ, «Изменить», сброс) — показываем его текстом.
  useEffect(() => {
    const incoming = props.doc;
    if (incoming === lastEmitted.current) return;
    const labels = propsRef.current.labels || {};
    const current = parse(textRef.current, labels);
    if (current && docKey(current) === docKey(incoming)) return;
    const next = docText(incoming, labels);
    lastEmitted.current = incoming;
    textRef.current = next;
    // Поле полуконтролируемое: свой текст, пока человек пишет, и чужой — когда документ пришёл извне.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setText(next);
    // Новый документ пришёл целиком — пусть уходит он, а не его текстовая копия.
    if (dirty.current) propsRef.current.onPromptText?.(null);
    dirty.current = false;
  }, [props.doc]);

  // Лоток изменился (перестановка, выключили фото): номера в тексте должны
  // идти за фото, как чипы в TipTap. Разбираем текст по меткам, с которыми
  // человек его видел, и показываем заново с новыми номерами — иначе «@Image 1»
  // после перестановки молча указал бы на другое фото.
  const labelsKey = useMemo(() => JSON.stringify(props.labels || {}), [props.labels]);
  const shownLabels = useRef<RefLabels>(props.labels || {});
  useEffect(() => {
    const prev = shownLabels.current;
    const next = propsRef.current.labels || {};
    shownLabels.current = next;
    const doc = dirty.current ? parse(textRef.current, prev) : propsRef.current.doc;
    if (!doc) return;
    const value = docText(doc, next);
    if (value === textRef.current) return;
    textRef.current = value;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setText(value);
    if (dirty.current) emit(value);
  }, [labelsKey, emit]);

  // Высота по содержимому (до 40vh), в полноэкранном режиме — на всё окно.
  useLayoutEffect(() => {
    const el = areaRef.current;
    if (!el) return;
    if (fullscreen) {
      el.style.height = "";
      return;
    }
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, Math.round(window.innerHeight * 0.4))}px`;
  }, [text, fullscreen]);

  useEffect(() => {
    if (props.autoFocus) areaRef.current?.focus();
  }, [props.autoFocus]);

  const showNotice = useCallback(
    (msg: string) => {
      setNotice(msg);
      later(() => setNotice((cur) => (cur === msg ? null : cur)), 6000);
    },
    [later],
  );

  const limitNotice = useCallback(
    () =>
      showNotice(
        tx(
          "editor.limit",
          "Больше {{max}} символов не поместится — ничего не обрезали, но и не вставили. Сократите текст или разбейте на несколько запросов.",
          { max: maxChars.toLocaleString("ru-RU") },
        ),
      ),
    [showNotice, tx, maxChars],
  );

  const setAtState = useCallback((next: AtState | null) => {
    atRef.current = next;
    setAt(next);
  }, []);

  const syncAt = useCallback(
    (value: string, caret: number) => {
      const hit = atBeforeCaret(value, caret);
      const prev = atRef.current;
      setAtState(hit ? { query: hit.query, from: hit.from, to: caret, via: prev?.via ?? "at" } : null);
    },
    [setAtState],
  );

  const onChangeText = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value.replace(/\r\n?/g, "\n");
    if (cpLength(value) > maxChars && cpLength(value) > cpLength(textRef.current)) {
      // Ввод сверх предела не принимаем (и не режем молча) — объясняем почему.
      e.target.value = textRef.current;
      limitNotice();
      return;
    }
    textRef.current = value;
    setText(value);
    emit(value);
    syncAt(value, e.target.selectionStart ?? value.length);
  };

  /** Вставить строку вместо [from, to] (по умолчанию — вместо выделения). */
  const insertAt = useCallback(
    (insert: string, range?: { from: number; to: number }) => {
      const el = areaRef.current;
      const value = textRef.current;
      const from = Math.min(range ? range.from : el?.selectionStart ?? value.length, value.length);
      const to = Math.min(range ? range.to : el?.selectionEnd ?? value.length, value.length);
      const next = value.slice(0, from) + insert + value.slice(to);
      if (cpLength(next) > maxChars && cpLength(next) > cpLength(value)) {
        limitNotice();
        return false;
      }
      applyText(next, from + insert.length);
      el?.focus();
      return true;
    },
    [applyText, limitNotice, maxChars],
  );

  /**
   * Теги «@Image N» для загруженных/выбранных материалов в позицию pos.
   * Номер появляется, когда родитель положит фото в лоток, — ждём до 5 с.
   */
  const insertTags = useCallback(
    (uids: Uid[], pos: number, via: MentionVia | null) => {
      if (!uids.length) return;
      const deadline = Date.now() + TAG_WAIT_MS;
      const attempt = () => {
        const labels = propsRef.current.labels || {};
        const known = uids.filter((u) => labels[u]);
        if (known.length < uids.length && Date.now() < deadline) {
          later(attempt, 120);
          return;
        }
        if (!known.length) return;
        const value = textRef.current;
        const at0 = Math.min(pos, value.length);
        const before = value.slice(0, at0);
        const lead = before && !/\s$/.test(before) ? " " : "";
        if (insertAt(`${lead}${known.map((u) => copyTagFor(labels[u])).join(" ")} `, { from: at0, to: at0 }) && via) {
          mention(via);
        }
      };
      attempt();
    },
    [insertAt, later, mention],
  );

  const upload = useCallback(
    async (files: File[], kind: "paste" | "drop" | "picker", via: MentionVia) => {
      const pos = areaRef.current?.selectionStart ?? textRef.current.length;
      let uids: Uid[] = [];
      try {
        uids = (await propsRef.current.onUpload(files, kind)) || [];
      } catch {
        uids = [];
      }
      insertTags(uids, pos, via);
    },
    [insertTags],
  );

  const closePicker = useCallback(() => setAtState(null), [setAtState]);

  const pick = useCallback(
    (item: PickerItem) => {
      const s = atRef.current;
      closePicker();
      const range = s ? { from: s.from, to: s.to } : undefined;
      const via = s?.via ?? "button";
      const label = propsRef.current.labels?.[item.asset];
      if (item.section === "in_request" && label) {
        if (insertAt(`${copyTagFor(label)} `, range)) mention(via);
        return;
      }
      if (range) insertAt("", range);
      propsRef.current.onPickLibrary?.(item.asset);
      insertTags([item.asset], range ? range.from : areaRef.current?.selectionStart ?? textRef.current.length, via);
    },
    [closePicker, insertAt, insertTags, mention],
  );

  const onAction = useCallback(
    (action: PickerAction) => {
      const s = atRef.current;
      closePicker();
      if (s) insertAt("", { from: s.from, to: s.to });
      if (action === "upload") {
        uploadVia.current = s?.via ?? "button";
        fileInput.current?.click();
      } else {
        propsRef.current.onGenerate();
      }
    },
    [closePicker, insertAt],
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      propsRef.current.onSubmit();
      return;
    }
    if (!atRef.current) return;
    if (e.key === "Escape") {
      e.preventDefault();
      closePicker();
      return;
    }
    if (pickerHandle.current?.keyDown(e.nativeEvent)) e.preventDefault();
  };

  const onSelect = (e: React.SyntheticEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget;
    if (atRef.current && el.selectionStart !== atRef.current.to) syncAt(el.value, el.selectionStart ?? 0);
  };

  const onPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const files = imageFiles(e.clipboardData);
    if (files.length) {
      e.preventDefault();
      void upload(files, "paste", "paste");
      return;
    }
    const pasted = e.clipboardData.getData("text/plain");
    const el = e.currentTarget;
    const selected = cpLength(el.value.slice(el.selectionStart ?? 0, el.selectionEnd ?? 0));
    if (pasted && cpLength(textRef.current) - selected + cpLength(pasted) > maxChars) {
      e.preventDefault();
      limitNotice();
    }
  };

  const onDrop = (e: React.DragEvent<HTMLTextAreaElement>) => {
    const files = imageFiles(e.dataTransfer);
    if (!files.length) return;
    // Не stopPropagation: DropOverlay должен снять подсветку; загрузку он
    // пропустит сам (defaultPrevented).
    e.preventDefault();
    void upload(files, "drop", "paste");
  };

  useImperativeHandle(
    props.handleRef,
    () => ({
      focus: () => areaRef.current?.focus(),
      insertRef: (asset: Uid) => insertTags([asset], areaRef.current?.selectionStart ?? textRef.current.length, null),
      openPicker: () => {
        const el = areaRef.current;
        const caret = el?.selectionStart ?? textRef.current.length;
        setAtState({ query: "", from: caret, to: caret, via: "button" });
        el?.focus();
      },
    }),
    [insertTags, setAtState],
  );

  const anchor = useCallback(() => areaRef.current?.getBoundingClientRect() ?? null, []);
  const pickerOwner = useCallback(() => areaRef.current, []);
  const placeholder =
    props.placeholder || tx("composer.placeholder", "Опишите, что происходит в кадре… Нажмите @, чтобы вставить фото");

  return (
    <EditorFrame
      fullscreen={fullscreen}
      onFullscreenChange={setFullscreen}
      notice={notice}
      chars={cpLength(text)}
      max={maxChars}
      hostRef={hostRef}
      onMoved={() => areaRef.current?.focus()}
      className={props.className}
    >
      <textarea
        ref={areaRef}
        value={text}
        onChange={onChangeText}
        onKeyDown={onKeyDown}
        onSelect={onSelect}
        onPaste={onPaste}
        onDrop={onDrop}
        disabled={props.disabled}
        rows={2}
        spellCheck
        enterKeyHint="enter"
        aria-label={props.ariaLabel || placeholder}
        placeholder={placeholder}
        // 15 px — только с мышью: на сенсорном экране iOS приближает страницу при фокусе в поле мельче 16 px.
        className={`block w-full resize-none bg-transparent px-1.5 py-1.5 pr-11 text-base leading-relaxed text-foreground caret-vs-accent outline-none placeholder:text-muted-2 md:pointer-fine:text-[15px] max-md:pr-12 ${
          fullscreen ? "min-h-0 flex-1" : "min-h-[3.25rem]"
        }`}
      />
      <div className="px-1.5 pb-1 text-[11px] text-muted-2">
        {tx("editor.fallbackHint", "Упрощённый редактор: пишите теги как @Image 1 — они распознаются при отправке.")}
      </div>
      <input
        ref={fileInput}
        type="file"
        accept="image/*,.heic,.heif"
        multiple
        className="hidden"
        tabIndex={-1}
        aria-hidden
        onChange={(e) => {
          const files = Array.from(e.target.files || []);
          e.target.value = "";
          if (files.length) void upload(files, "picker", uploadVia.current);
        }}
      />
      <MentionPicker
        open={Boolean(at) && !props.disabled}
        query={at?.query || ""}
        items={props.pickerItems}
        labels={props.labels}
        anchor={anchor}
        mobile={mobile}
        onPick={pick}
        onAction={onAction}
        onClose={closePicker}
        insideRef={hostRef}
        handleRef={pickerHandle}
        owner={pickerOwner}
      />
    </EditorFrame>
  );
}
