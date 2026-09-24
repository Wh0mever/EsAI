/**
 * Видеостудия, редактор промпта: помощники без TipTap.
 *
 * Их берёт и запасная textarea, которая лежит в основном куске страницы
 * (она нужна именно тогда, когда кусок с TipTap не загрузился). Поэтому
 * здесь нельзя импортировать @tiptap/* — иначе весь редактор уехал бы в
 * основной кусок и ленивая загрузка (next/dynamic) потеряла бы смысл.
 */

/**
 * Что может стоять перед «@», чтобы открылся выбор: пробел, начало строки,
 * скобка или кавычка. «mail@site» — не открывает.
 */
export const ALLOWED_PREFIXES = [" ", String.fromCharCode(0xa0), "\t", "(", "«", "\"", "'", "“", "„", "‘"];

const AT_RE = /@([^\s@]{0,40})$/u;

/**
 * «@запрос» прямо перед курсором в обычном тексте (запасная textarea) — по тем
 * же правилам, что Suggestion: перед «@» пробел, скобка, кавычка или начало строки.
 */
export function atBeforeCaret(text: string, caret: number): { query: string; from: number } | null {
  const head = text.slice(0, caret);
  const m = AT_RE.exec(head);
  if (!m) return null;
  const from = caret - m[0].length;
  const prev = from > 0 ? head[from - 1] : "";
  if (prev && prev !== "\n" && !ALLOWED_PREFIXES.includes(prev)) return null;
  return { query: m[1], from };
}

const IMAGE_EXT = /\.(jpe?g|png|webp|gif|heic|heif|avif|bmp)$/i;

/** Картинки из DataTransfer (HEIC у части браузеров приходит без type — смотрим и расширение). */
export function imageFiles(dt: DataTransfer | null | undefined): File[] {
  if (!dt) return [];
  const out: File[] = [];
  const push = (f: File | null) => {
    if (f && (f.type.startsWith("image/") || IMAGE_EXT.test(f.name || "")) && !out.includes(f)) out.push(f);
  };
  if (dt.files && dt.files.length) {
    for (const f of Array.from(dt.files)) push(f);
  } else if (dt.items && dt.items.length) {
    for (const it of Array.from(dt.items)) if (it.kind === "file") push(it.getAsFile());
  }
  return out;
}

/** Телефон: ширина меньше 768 px (§9.7). */
export const MOBILE_QUERY = "(max-width: 767px)";
