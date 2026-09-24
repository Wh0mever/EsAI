"use client";

/**
 * Видеостудия: редактор промпта на TipTap v3 (§9.5). Грузится только через
 * PromptEditor (next/dynamic, ssr:false) — на остальных страницах его нет.
 *
 * Минимальная схема: doc > paragraph > text | hardBreak | vsRef. Документ
 * наружу — prompt_doc v1 (promptDoc.tiptapToDoc), внутрь — docToTiptap.
 * Метки чипов считает родитель (labels.ts) и передаёт пропсом labels.
 *
 * Что умеет:
 *  - «@» и кнопка «@ Материалы» → MentionPicker (в запросе / мои материалы /
 *    загрузить / создать картинку), ↑↓ Enter Esc, фильтр по вводу;
 *  - вставка текста с тегами → чипы (грамматика сервера), вставка и
 *    перетаскивание картинок → загрузка и чип в позиции курсора;
 *  - копирование → «@Image N»; дописанный руками тег → чип;
 *  - Ctrl/⌘+Enter — «Создать», Enter — новый абзац, Shift+Enter — перенос строки;
 *  - предел 20 000 символов и 64 ссылок без молчаливой обрезки;
 *  - полноэкранный режим (EditorFrame), Esc сворачивает его.
 */
import { Extension, type Editor } from "@tiptap/core";
import Document from "@tiptap/extension-document";
import HardBreak from "@tiptap/extension-hard-break";
import Paragraph from "@tiptap/extension-paragraph";
import Text from "@tiptap/extension-text";
import { Placeholder } from "@tiptap/extensions/placeholder";
import { UndoRedo } from "@tiptap/extensions/undo-redo";
import { Selection } from "@tiptap/pm/state";
import type { EditorView } from "@tiptap/pm/view";
import { EditorContent, useEditor } from "@tiptap/react";
import { useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { trackVs } from "@/lib/vstudio/api";
import { indexFromLabels } from "@/lib/vstudio/labels";
import {
  docKey,
  docTextLength,
  docToTiptap,
  REF_NODE,
  tiptapToDoc,
  type TagIndex,
  type TiptapJSON,
} from "@/lib/vstudio/promptDoc";
import { PROMPT_MAX_CHARS } from "@/lib/vstudio/types";
import type { MentionVia, PickerItem, PromptDoc, Uid } from "@/lib/vstudio/types";
import EditorFrame from "./EditorFrame";
import type { VsPromptEditorProps } from "./editorTypes";
import { MOBILE_QUERY } from "./inputHelpers";
import MentionPicker, { type MentionPickerHandle, type PickerAction } from "./MentionPicker";
import {
  addPending,
  EXTERNAL_META,
  finishTags,
  forceRelink,
  imageFiles,
  limitPlugin,
  OBJECT_CHAR,
  pendingPlugin,
  refInsertTransaction,
  relinkPlugin,
  relinkSlice,
  sliceFits,
  sliceFromText,
  takePending,
  type LimitKind,
} from "./pasteRelink";
import { RefStore, VsRef } from "./vsRef";
import { closeMention, isMentionActive, openAt, VsMention, type MentionBridge, type MentionSession } from "./suggestion";

/** Стили, которых нет в Tailwind-классах: плейсхолдер, подчёркивание тегов, метка загрузки. */
const EDITOR_CSS = `
.vs-editor.ProseMirror p { margin: 0; }
.vs-editor.ProseMirror p.is-editor-empty:first-child::before {
  content: attr(data-placeholder); float: left; height: 0; pointer-events: none; color: var(--muted-2);
}
.vs-editor.ProseMirror .vs-chip { white-space: nowrap; }
.vs-editor.ProseMirror .ProseMirror-selectednode { outline: none; }
.vs-editor.ProseMirror .suggestion { color: var(--accent-text); }
.vs-editor.ProseMirror .vs-tag-issue {
  text-decoration: underline wavy var(--status-fail); text-underline-offset: 3px; text-decoration-skip-ink: none;
}
.vs-editor.ProseMirror .vs-pending {
  display: inline-block; margin: 0 1px; padding: 0 0.4em; border-radius: 0.375rem;
  background: var(--surface-3); color: var(--muted); font-size: 0.92em; animation: vs-pending 1.2s ease-in-out infinite;
}
.vs-editor.ProseMirror .vs-pending:empty { display: none; }
@keyframes vs-pending { 50% { opacity: 0.45; } }
@media (prefers-reduced-motion: reduce) { .vs-editor.ProseMirror .vs-pending { animation: none; } }
`;

type PickerState = MentionSession;

/** Телефон: ширина меньше 768 px (§9.7). */
function useIsMobile(): boolean {
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia(MOBILE_QUERY);
    const read = () => setMobile(mq.matches);
    read();
    mq.addEventListener?.("change", read);
    return () => mq.removeEventListener?.("change", read);
  }, []);
  return mobile;
}

export default function TipTapPromptEditor(props: VsPromptEditorProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const tx = useCallback(
    (key: string, ru: string, opts?: Record<string, unknown>) => String(t(key, { defaultValue: ru, ...(opts || {}) })),
    [t],
  );
  const propsRef = useRef(props);
  const txRef = useRef(tx);
  useLayoutEffect(() => {
    propsRef.current = props;
    txRef.current = tx;
  });

  const maxChars = props.maxChars ?? PROMPT_MAX_CHARS;
  const mobile = useIsMobile();
  // Метки — сразу при создании: иначе чипы на первом кадре мигнули бы красным «нет в запросе».
  const [store] = useState(() => new RefStore(props.labels));
  const [initialContent] = useState(() => docToTiptap(props.doc));
  useEffect(() => () => store.dispose(), [store]);
  const [picker, setPicker] = useState<PickerState | null>(null);
  const pickerRef = useRef<PickerState | null>(null);
  const pickerHandle = useRef<MentionPickerHandle | null>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const editorRef = useRef<Editor | null>(null);
  const [initialIndex] = useState(() => indexFromLabels(props.labels || {}));
  const indexRef = useRef<TagIndex>(initialIndex);
  /** Как открыли список: «@» с клавиатуры или кнопкой (для воронки). */
  const viaRef = useRef<MentionVia>("at");
  /** «@», вставленный кнопкой: при отмене его убираем. */
  const buttonAt = useRef<{ from: number; to: number } | null>(null);
  /** Куда поставить чипы после выбора файлов в «Загрузить фото». */
  const uploadAt = useRef<{ id: string; via: MentionVia } | null>(null);
  const lastEmitted = useRef<{ doc: PromptDoc; key: string | null } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [chars, setChars] = useState(() => docTextLength(props.doc));
  const [innerFull, setInnerFull] = useState(false);
  const fullscreen = props.fullscreen ?? innerFull;
  const fullscreenRef = useRef(fullscreen);
  useLayoutEffect(() => {
    fullscreenRef.current = fullscreen;
  }, [fullscreen]);

  const setFullscreen = useCallback((open: boolean) => {
    const cb = propsRef.current.onFullscreenChange;
    if (cb) cb(open);
    if (propsRef.current.fullscreen === undefined) setInnerFull(open);
  }, []);

  const showNotice = useCallback((text: string) => {
    setNotice(text);
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    noticeTimer.current = setTimeout(() => setNotice(null), 6000);
  }, []);
  useEffect(
    () => () => {
      if (noticeTimer.current) clearTimeout(noticeTimer.current);
    },
    [],
  );

  const onLimit = useCallback(
    (kind: LimitKind) => {
      const max = propsRef.current.maxChars ?? PROMPT_MAX_CHARS;
      showNotice(
        kind === "chars"
          ? txRef.current(
              "editor.limit",
              "Больше {{max}} символов не поместится — ничего не обрезали, но и не вставили. Сократите текст или разбейте на несколько запросов.",
              { max: max.toLocaleString("ru-RU") },
            )
          : txRef.current("editor.refsLimit", "В одном тексте не больше 64 упоминаний фото."),
      );
    },
    [showNotice],
  );

  const mention = useCallback((via: MentionVia) => {
    const cb = propsRef.current.onMention;
    if (cb) cb(via);
    else trackVs("vstudio_mention", { via });
  }, []);

  /* ---------------- вставка чипов и загрузка ---------------- */

  const insertRefs = useCallback(
    (view: EditorView, from: number, to: number, uids: Uid[], via: MentionVia | null) => {
      if (view.isDestroyed || !uids.length) return false;
      store.expect(uids.filter((u) => !store.labels[u]));
      const tr = refInsertTransaction(view.state, from, to, uids);
      if (!tr) return false;
      view.dispatch(tr.scrollIntoView());
      if (via) mention(via);
      return true;
    },
    [store, mention],
  );

  const uploadAndInsert = useCallback(
    async (files: File[], pendingId: string, kind: "paste" | "drop" | "picker", via: MentionVia) => {
      const view = editorRef.current?.view;
      let uids: Uid[] = [];
      try {
        uids = (await propsRef.current.onUpload(files, kind)) || [];
      } catch {
        uids = [];
      }
      const live = editorRef.current?.view;
      if (!live || live !== view || live.isDestroyed) return;
      const at = takePending(live, pendingId);
      if (at == null || !uids.length) return;
      insertRefs(live, at, at, uids, via);
    },
    [insertRefs],
  );

  const startUpload = useCallback(
    (view: EditorView, files: File[], pos: number, kind: "paste" | "drop" | "picker", via: MentionVia) => {
      const id = addPending(view, pos, txRef.current("editor.uploading", "Загрузка…"));
      void uploadAndInsert(files, id, kind, via);
    },
    [uploadAndInsert],
  );

  /* ---------------- мост «@» → React ---------------- */

  const bridge = useMemo<MentionBridge>(
    () => ({
      open: (s) => {
        pickerRef.current = s;
        setPicker(s);
      },
      update: (s) => {
        pickerRef.current = s;
        setPicker(s);
      },
      close: (reason) => {
        const s = pickerRef.current;
        pickerRef.current = null;
        setPicker(null);
        if (reason === "escape") dropButtonAt(s);
        else {
          viaRef.current = "at";
          buttonAt.current = null;
        }
      },
      keyDown: (e) => pickerHandle.current?.keyDown(e) ?? false,
    }),
    [],
  );

  /** Кнопка открыла «@», а человек передумал: убираем этот «@» из текста. */
  function dropButtonAt(s: PickerState | null) {
    const at = buttonAt.current;
    buttonAt.current = null;
    viaRef.current = "at";
    const view = editorRef.current?.view;
    if (!at || !view || view.isDestroyed || (s && s.query)) return;
    const size = view.state.doc.content.size;
    if (at.to > size) return;
    const text = view.state.doc.textBetween(at.from, at.to, "\n", OBJECT_CHAR);
    if (text.trim() === "@") view.dispatch(view.state.tr.delete(at.from, at.to));
  }

  /* ---------------- расширения ---------------- */

  const extensions = useMemo(() => {
    const submit = () => {
      const view = editorRef.current?.view;
      if (view?.composing) return false;
      // Тег, за которым ещё стоит курсор («…в стиле @Image 1|»), — тоже чип:
      // иначе запрос ушёл бы с буквальным текстом тега. Документ поменялся —
      // «Создать» после рендера, чтобы цена и тело запроса были уже новыми.
      if (view && finishTags(view, indexRef.current)) {
        setTimeout(() => propsRef.current.onSubmit(), 0);
        return true;
      }
      propsRef.current.onSubmit();
      return true;
    };
    // Esc во весь экран — свернуть. ProseMirror гасит Esc сам (preventDefault),
    // поэтому слушатель рамки его не видит; открытый список «@» Esc забирает раньше.
    const escape = () => {
      const ed = editorRef.current;
      if (!ed || isMentionActive(ed.state) || !fullscreenRef.current) return false;
      setFullscreen(false);
      return true;
    };
    const Keys = Extension.create({
      name: "vsEditorKeys",
      priority: 1100,
      addKeyboardShortcuts() {
        return { "Mod-Enter": submit, "Ctrl-Enter": submit, Escape: escape };
      },
      addProseMirrorPlugins() {
        return [
          relinkPlugin({
            getIndex: () => indexRef.current,
            texts: () => ({
              unknown: (raw) =>
                txRef.current("warnings.tag_unknown", "«{{text}}» похоже на тег, но такого фото в запросе нет.", { text: raw }),
              media: txRef.current(
                "errors.video_refs_unsupported",
                "Видео и звук как референсы появятся позже. Сейчас можно добавить только фото.",
              ),
            }),
          }),
          limitPlugin({ getMax: () => propsRef.current.maxChars ?? PROMPT_MAX_CHARS, onLimit }),
          pendingPlugin(),
        ];
      },
    });
    return [
      Document,
      Paragraph,
      Text,
      // Ctrl/⌘+Enter — «Создать»; перенос строки внутри абзаца — только Shift+Enter.
      HardBreak.extend({
        addKeyboardShortcuts() {
          return { "Shift-Enter": () => this.editor.commands.setHardBreak() };
        },
      }),
      UndoRedo,
      Placeholder.configure({
        placeholder: () =>
          propsRef.current.placeholder ||
          txRef.current("composer.placeholder", "Опишите, что происходит в кадре… Нажмите @, чтобы вставить фото"),
      }),
      VsRef.configure({ store }),
      VsMention.configure({ bridge }),
      Keys,
    ];
  }, [store, bridge, onLimit, setFullscreen]);

  /* ---------------- вставка и перетаскивание ---------------- */

  const editorProps = useMemo(
    () => ({
      attributes: {
        class:
          "vs-editor min-h-[4.75rem] px-3 py-2.5 pr-11 text-base leading-relaxed text-foreground outline-none md:text-[15px] max-md:pr-12",
        role: "textbox",
        "aria-multiline": "true",
        "aria-label":
          props.ariaLabel ||
          props.placeholder ||
          tx("composer.placeholder", "Опишите, что происходит в кадре… Нажмите @, чтобы вставить фото"),
        spellcheck: "true",
        autocapitalize: "sentences",
        enterkeyhint: "enter",
      },
      handlePaste: (view: EditorView, event: ClipboardEvent) => {
        const files = imageFiles(event.clipboardData);
        if (files.length) {
          event.preventDefault();
          const { from, to } = view.state.selection;
          if (from !== to) view.dispatch(view.state.tr.delete(from, to));
          startUpload(view, files, view.state.selection.from, "paste", "paste");
          return true;
        }
        const html = event.clipboardData?.getData("text/html") || "";
        // Копия из самого редактора: HTML несёт uid чипов — пусть разбирает ProseMirror (transformPasted).
        if (html.includes("data-vs-ref")) return false;
        const text = event.clipboardData?.getData("text/plain") || "";
        if (!text) return false;
        // Внешний текст — всегда как text/plain: переносы строк доходят ровно такими, как у человека.
        const { slice, refs } = sliceFromText(view.state.schema, text, indexRef.current);
        const over = sliceFits(view.state, slice, propsRef.current.maxChars ?? PROMPT_MAX_CHARS);
        if (over) {
          event.preventDefault();
          onLimit(over);
          return true;
        }
        event.preventDefault();
        view.dispatch(view.state.tr.replaceSelection(slice).scrollIntoView().setMeta("paste", true).setMeta("uiEvent", "paste"));
        if (refs) mention("paste");
        return true;
      },
      handleDrop: (view: EditorView, event: DragEvent, _slice: unknown, moved: boolean) => {
        if (moved) return false;
        const files = imageFiles(event.dataTransfer);
        if (!files.length) return false;
        // Картинку бросили в текст — чип встанет в точку броска. Дальше событие
        // не глушим: зоне композера (DropOverlay) надо убрать подсветку, а
        // загрузку она пропустит сама — defaultPrevented.
        event.preventDefault();
        const pos = view.posAtCoords({ left: event.clientX, top: event.clientY })?.pos ?? view.state.selection.from;
        startUpload(view, files, pos, "drop", "paste");
        return true;
      },
      clipboardTextParser: (text: string, _ctx: unknown, _plain: boolean, view: EditorView) =>
        sliceFromText(view.state.schema, text, indexRef.current).slice,
      transformPasted: (slice: Parameters<typeof relinkSlice>[0], view: EditorView) =>
        relinkSlice(slice, view.state.schema, indexRef.current, (uid) => Boolean(store.labels[uid])),
      handleClickOn: (_view: EditorView, _pos: number, node: { type: { name: string }; attrs: Record<string, unknown> }) => {
        if (node.type.name === REF_NODE && typeof node.attrs.asset === "string") propsRef.current.onRefClick?.(node.attrs.asset);
        return false;
      },
    }),
    // Атрибуты задаются при создании редактора; обработчики читают свежие пропсы через ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const emit = useCallback((editor: Editor) => {
    const doc = tiptapToDoc(editor.getJSON() as TiptapJSON);
    lastEmitted.current = { doc, key: null };
    setChars(docTextLength(doc));
    propsRef.current.onChange(doc);
  }, []);

  const editor = useEditor(
    {
      extensions,
      content: initialContent,
      editable: !props.disabled,
      autofocus: props.autoFocus ? "end" : false,
      immediatelyRender: true,
      shouldRerenderOnTransaction: false,
      coreExtensionOptions: { clipboardTextSerializer: { blockSeparator: "\n" } },
      editorProps,
      onUpdate: ({ editor: ed, transaction }) => {
        if (transaction.getMeta(EXTERNAL_META)) return;
        emit(ed);
      },
      // Ушёл из поля (в том числе к кнопке «Создать») — набранный тег дописан.
      onBlur: ({ editor: ed }) => {
        if (!ed.isDestroyed) finishTags(ed.view, indexRef.current);
      },
    },
    [extensions],
  );

  useLayoutEffect(() => {
    editorRef.current = editor;
  }, [editor]);

  /* ---------------- пропсы → редактор ---------------- */

  // Документ сменился снаружи (Сжать с ИИ, «Изменить», сброс после запуска).
  useEffect(() => {
    if (!editor || editor.isDestroyed) return;
    const incoming = props.doc;
    const last = lastEmitted.current;
    if (last && incoming === last.doc) return;
    const key = docKey(incoming);
    if (last) {
      if (last.key === null) last.key = docKey(last.doc);
      if (key === last.key) return;
    }
    const current = tiptapToDoc(editor.getJSON() as TiptapJSON);
    if (docKey(current) === key) {
      lastEmitted.current = { doc: incoming, key };
      return;
    }
    const node = editor.schema.nodeFromJSON(docToTiptap(incoming));
    const tr = editor.state.tr.replaceWith(0, editor.state.doc.content.size, node.content).setMeta(EXTERNAL_META, true);
    tr.setSelection(Selection.atEnd(tr.doc));
    editor.view.dispatch(tr);
    lastEmitted.current = { doc: incoming, key };
    setChars(docTextLength(incoming));
  }, [editor, props.doc]);

  // Метки: перенумерация перерисовывает чипы, новые номера перепривязывают теги-текст.
  const labelsKey = useMemo(() => JSON.stringify(props.labels || {}), [props.labels]);
  useEffect(() => {
    store.translate = t as unknown as RefStore["translate"];
    store.setLabels(propsRef.current.labels || {});
    indexRef.current = indexFromLabels(propsRef.current.labels || {});
    const view = editor && !editor.isDestroyed ? editor.view : null;
    if (!view) return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const run = () => {
      if (view.isDestroyed) return;
      // Во время композиции (Gboard) документ не трогаем — дождёмся её конца.
      if (view.composing) timer = setTimeout(run, 300);
      else forceRelink(view);
    };
    run();
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [editor, labelsKey, store, t]);

  useEffect(() => {
    if (editor && !editor.isDestroyed) editor.setEditable(!props.disabled);
    if (props.disabled && editor && !editor.isDestroyed) closeMention(editor.view);
  }, [editor, props.disabled]);

  /* ---------------- выбор материала ---------------- */

  const pick = useCallback(
    (item: PickerItem) => {
      const view = editorRef.current?.view;
      const s = pickerRef.current;
      if (!view || view.isDestroyed || !s) return;
      if (item.section === "library") propsRef.current.onPickLibrary?.(item.asset);
      buttonAt.current = null;
      insertRefs(view, s.range.from, s.range.to, [item.asset], viaRef.current);
      view.focus();
    },
    [insertRefs],
  );

  const onAction = useCallback(
    (action: PickerAction) => {
      const view = editorRef.current?.view;
      const s = pickerRef.current;
      if (!view || view.isDestroyed || !s) return;
      const via = viaRef.current;
      buttonAt.current = null;
      // «@запрос» больше не нужен: чип (или картинка) встанет на его место.
      view.dispatch(view.state.tr.delete(s.range.from, s.range.to));
      if (action === "upload") {
        if (uploadAt.current) takePending(view, uploadAt.current.id);
        uploadAt.current = { id: addPending(view, s.range.from, ""), via };
        fileInput.current?.click();
      } else {
        propsRef.current.onGenerate();
      }
    },
    [],
  );

  const onFilesChosen = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      e.target.value = "";
      const view = editorRef.current?.view;
      const at = uploadAt.current;
      uploadAt.current = null;
      if (!view || view.isDestroyed || !at) return;
      const pos = takePending(view, at.id);
      if (!files.length || pos == null) return;
      startUpload(view, files, pos, "picker", at.via);
    },
    [startUpload],
  );

  // Выбор файлов отменили — метка позиции больше не нужна.
  useEffect(() => {
    const input = fileInput.current;
    if (!input) return;
    const onCancel = () => {
      const view = editorRef.current?.view;
      const at = uploadAt.current;
      uploadAt.current = null;
      if (view && at) takePending(view, at.id);
    };
    input.addEventListener("cancel", onCancel);
    return () => input.removeEventListener("cancel", onCancel);
  }, []);

  const closePicker = useCallback(() => {
    const view = editorRef.current?.view;
    const s = pickerRef.current;
    if (!view || view.isDestroyed) return;
    dropButtonAt(s);
    closeMention(view);
  }, []);

  /* ---------------- ручки для родителя ---------------- */

  useImperativeHandle(
    props.handleRef,
    () => ({
      focus: () => {
        const ed = editorRef.current;
        if (ed && !ed.isDestroyed) ed.commands.focus();
      },
      insertRef: (asset: Uid) => {
        const view = editorRef.current?.view;
        if (!view || view.isDestroyed) return;
        const { from, to } = view.state.selection;
        insertRefs(view, from, to, [asset], null);
        view.focus();
      },
      openPicker: () => {
        const ed = editorRef.current;
        if (!ed || ed.isDestroyed || !ed.isEditable) return;
        if (isMentionActive(ed.state)) {
          ed.view.focus();
          return;
        }
        viaRef.current = "button";
        buttonAt.current = openAt(ed.view);
      },
    }),
    [insertRefs],
  );

  // Поле с фокусом для a11y списка «@» (aria-activedescendant — на нём).
  const pickerOwner = useCallback((): HTMLElement | null => {
    const ed = editorRef.current;
    if (!ed || ed.isDestroyed) return null;
    try {
      return ed.view.dom as HTMLElement;
    } catch {
      return null;
    }
  }, []);

  const refocus = useCallback(() => {
    const ed = editorRef.current;
    if (ed && !ed.isDestroyed) ed.commands.focus();
  }, []);

  return (
    <EditorFrame
      fullscreen={fullscreen}
      onFullscreenChange={setFullscreen}
      notice={notice}
      chars={chars}
      max={maxChars}
      hostRef={hostRef}
      onMoved={refocus}
      className={props.className}
    >
      <style href="vs-prompt-editor" precedence="default">
        {EDITOR_CSS}
      </style>
      {/* Высота — от видимой части окна (--vvh): vh не уменьшается, когда на
          телефоне открыта клавиатура, и поле выталкивало «Создать» за край. */}
      <div
        className={
          fullscreen
            ? "min-h-0 flex-1 overflow-y-auto"
            : "max-h-[40vh] overflow-y-auto overscroll-contain max-md:max-h-[calc(var(--vvh,100dvh)*0.3)]"
        }
      >
        {/* Во весь экран поле тянется до низа: клик в пустоту под текстом ставит курсор. */}
        <EditorContent editor={editor} className={fullscreen ? "flex min-h-full flex-col [&>.vs-editor]:flex-1" : ""} />
      </div>
      <input
        ref={fileInput}
        type="file"
        accept="image/*,.heic,.heif"
        multiple
        className="hidden"
        tabIndex={-1}
        aria-hidden
        onChange={onFilesChosen}
      />
      <MentionPicker
        open={Boolean(picker) && !props.disabled}
        query={picker?.query || ""}
        items={props.pickerItems}
        labels={props.labels}
        anchor={picker?.rect || (() => null)}
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
