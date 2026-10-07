#!/usr/bin/env node
/**
 * Паритет переводов: ru — эталон, en и kg должны его повторять (§10 видеостудии).
 *
 *   node scripts/i18n-parity.mjs vstudio        строгая проверка namespace vstudio
 *   node scripts/i18n-parity.mjs vstudio home   несколько строгих namespace
 *   node scripts/i18n-parity.mjs                только отчёт по всем, без падения
 *
 * Флаги: --no-code — не сверять с кодом; --verbose — печатать и мелочи
 * (неиспользуемые ключи, строки кода, похожие на ключи).
 *
 * Строгий namespace падает (exit 1), если:
 *  - ключа из ru нет в en/kg, или в en/kg есть ключ, которого нет в ru;
 *  - значение пустое или не строка, или один ключ — и текст, и группа;
 *  - подстановки {{x}} перевода не совпадают с ru;
 *  - пропала метка «@Image N» / «Image {{k}}» — она не переводится (§4.2);
 *  - у множественного числа нет форм, нужных языку.
 * Для namespace из CODE_SCAN (vstudio) ещё и сверка с кодом:
 *  - ключ, который код зовёт строкой (t("…"), таблицы *_RU, {key, ru}), есть в ru;
 *  - ru совпадает с русским defaultValue из кода — иначе человек увидит
 *    устаревший текст, хотя в коде его уже поправили.
 * Нестрогие namespace (common и т.д.) только печатают отставание en/kg от ru.
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

export const NEXT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const LANGS = ["ru", "en", "kg"];
export const REFERENCE = "ru";

const PLURAL_CATS = ["zero", "one", "two", "few", "many", "other"];
const PLURAL_RE = new RegExp(`^(.+)_(${PLURAL_CATS.join("|")})$`);

/**
 * Формы множественного числа, которые i18next спросит у языка.
 * «kg» для Intl — не киргизский (ky), а неизвестный код: правила возьмутся из
 * языка браузера по умолчанию. Поэтому kg должен иметь все формы ru и en.
 */
export function pluralCategories(lang) {
  if (lang === "kg") return ["one", "few", "many", "other"];
  try {
    return [...new Intl.PluralRules(lang).resolvedOptions().pluralCategories];
  } catch {
    return ["one", "other"];
  }
}

/* ------------------------------------------------------------------ */
/* Файлы                                                               */
/* ------------------------------------------------------------------ */

/**
 * Вложенный JSON → Map «a.b.c» → значение; ошибки формы — в problems.
 * Массивы (returnObjects в common.json) раскладываются по индексам «a.0.b»:
 * так видно и короткий массив в переводе.
 */
export function flatten(obj, prefix = "", out = new Map(), problems = []) {
  const entries = Array.isArray(obj) ? obj.map((v, i) => [String(i), v]) : Object.entries(obj || {});
  for (const [k, v] of entries) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (k.includes(".")) problems.push(`ключ с точкой внутри «${key}» не найдётся через t()`);
    if (v && typeof v === "object") {
      if (!Object.keys(v).length) problems.push(`пустая группа «${key}»`);
      flatten(v, key, out, problems);
    } else {
      out.set(key, v);
    }
  }
  return out;
}

export function localePath(root, lang, ns) {
  return path.join(root, "src", "locales", lang, `${ns}.json`);
}

export function loadLocale(root, lang, ns) {
  const file = localePath(root, lang, ns);
  if (!fs.existsSync(file)) return { file, missing: true, keys: new Map(), problems: [] };
  let data;
  try {
    const raw = fs.readFileSync(file, "utf8");
    // BOM от Windows-редакторов JSON.parse не прощает.
    data = JSON.parse(raw.charCodeAt(0) === 0xfeff ? raw.slice(1) : raw);
  } catch (e) {
    return { file, missing: false, keys: new Map(), problems: [`не JSON: ${e.message}`] };
  }
  const problems = [];
  const keys = flatten(data, "", new Map(), problems);
  return { file, missing: false, keys, problems };
}

export function listNamespaces(root) {
  const dir = path.join(root, "src", "locales", REFERENCE);
  return fs
    .readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .map((f) => f.slice(0, -5))
    .sort();
}

/* ------------------------------------------------------------------ */
/* Сверка двух языков                                                   */
/* ------------------------------------------------------------------ */

/** {{name}} и {{name, format}} → имена. */
export function placeholders(text) {
  const out = new Set();
  for (const m of String(text).matchAll(/\{\{\s*([\w.]+)\s*(?:,[^}]*)?\}\}/g)) out.add(m[1]);
  return out;
}

/**
 * Метки моделей «@Image {{n}}», «Image {{k}}», «@Image N», «@Image —» — не
 * переводятся (§4.2). Слово Image без номера (англ. «Image — 7 cr») — не метка.
 */
export function imageLabels(text) {
  return [...String(text).matchAll(/@Image —|@?Image (?:\{\{\s*\w+\s*\}\}|N\b|\d+)/g)].map((m) => m[0].replace(/\s+/g, " ")).sort();
}

/** Семейства множественного числа эталона: base → формы (нужны хотя бы _one и _other). */
export function pluralFamilies(keys) {
  const forms = new Map();
  for (const k of keys.keys()) {
    const m = PLURAL_RE.exec(k);
    if (!m) continue;
    if (!forms.has(m[1])) forms.set(m[1], new Set());
    forms.get(m[1]).add(m[2]);
  }
  const out = new Map();
  for (const [base, cats] of forms) if (cats.has("one") && cats.has("other")) out.set(base, cats);
  return out;
}

const sameSet = (a, b) => a.size === b.size && [...a].every((x) => b.has(x));
const fmtSet = (s) => (s.size ? [...s].sort().map((x) => `{{${x}}}`).join(" ") : "—");

/**
 * Сверить язык с эталоном. Возвращает {errors, warnings} — строки для печати.
 * ref, other — Map ключ → значение (flatten).
 */
export function comparePair(ref, other, lang, refLang = REFERENCE) {
  const errors = [];
  const warnings = [];
  const families = pluralFamilies(ref);
  const familyOf = (key) => {
    const m = PLURAL_RE.exec(key);
    return m && families.has(m[1]) ? m[1] : null;
  };

  // Обычные ключи эталона.
  for (const [key, value] of ref) {
    if (familyOf(key)) continue;
    if (!other.has(key)) {
      errors.push(`${lang}: нет ключа «${key}»`);
      continue;
    }
    compareValue(errors, lang, key, value, other.get(key));
  }

  // Множественное число: формы языка, плюс сверка подстановок по объединению форм.
  const need = pluralCategories(lang);
  for (const [base, refCats] of families) {
    const have = [...PLURAL_CATS].filter((c) => other.has(`${base}_${c}`));
    for (const c of need) if (!other.has(`${base}_${c}`)) errors.push(`${lang}: нет формы «${base}_${c}»`);
    if (!have.length) continue;
    const refPh = new Set();
    for (const c of refCats) for (const p of placeholders(ref.get(`${base}_${c}`))) refPh.add(p);
    const ph = new Set();
    for (const c of have) {
      const v = other.get(`${base}_${c}`);
      if (typeof v !== "string" || !v.trim()) errors.push(`${lang}: пустое значение «${base}_${c}»`);
      else for (const p of placeholders(v)) ph.add(p);
    }
    if (!sameSet(refPh, ph)) errors.push(`${lang}: «${base}_*» подстановки ${fmtSet(ph)}, а в ${refLang} ${fmtSet(refPh)}`);
  }

  // Лишнее в языке: удалённые из ru ключи тихо показывали бы старый текст.
  for (const key of other.keys()) {
    if (ref.has(key)) continue;
    const m = PLURAL_RE.exec(key);
    if (m && families.has(m[1])) continue;
    errors.push(`${lang}: лишний ключ «${key}» (нет в ${refLang})`);
  }
  return { errors, warnings };
}

/** Сверка одного значения: пустота, подстановки, метки Image. */
function compareValue(errors, lang, key, refValue, value) {
  if (typeof value !== "string") {
    errors.push(`${lang}: «${key}» — не строка`);
    return;
  }
  if (!value.trim()) {
    errors.push(`${lang}: пустое значение «${key}»`);
    return;
  }
  const a = placeholders(refValue);
  const b = placeholders(value);
  if (!sameSet(a, b)) errors.push(`${lang}: «${key}» подстановки ${fmtSet(b)}, а в ${REFERENCE} ${fmtSet(a)}`);
  const la = imageLabels(refValue).join("|");
  const lb = imageLabels(value).join("|");
  if (la !== lb) errors.push(`${lang}: «${key}» метки Image не совпадают с ${REFERENCE} (${la || "—"} ≠ ${lb || "—"})`);
}

/** Проверки самого эталона: форма значений. */
export function checkReference(ref, lang = REFERENCE) {
  const errors = [];
  for (const [key, value] of ref) {
    if (typeof value !== "string") errors.push(`${lang}: «${key}» — не строка`);
    else if (!value.trim()) errors.push(`${lang}: пустое значение «${key}»`);
  }
  // «a.b» — и текст, и группа: JSON такого не выразит, но flatten это увидит
  // при ключе с точкой; здесь — защита для Map, собранных не из JSON.
  const keys = new Set(ref.keys());
  for (const key of keys) {
    const parts = key.split(".");
    for (let i = 1; i < parts.length; i++) {
      const head = parts.slice(0, i).join(".");
      if (keys.has(head)) errors.push(`${lang}: «${head}» — и текст, и группа («${key}»)`);
    }
  }
  return errors;
}

/* ------------------------------------------------------------------ */
/* Сверка с кодом (vstudio)                                             */
/* ------------------------------------------------------------------ */

export const CODE_SCAN = {
  vstudio: {
    dirs: ["src/components/vstudio", "src/app/video-studio", "src/lib/vstudio"],
    // Таблицы русских текстов: откуда и как ключ таблицы становится ключом перевода.
    tables: [
      { file: "src/components/vstudio/composer/composerText.ts", name: "COMPOSER_RU", prefix: "" },
      { file: "src/components/vstudio/settings/settingsText.ts", name: "SETTINGS_RU", prefix: "" },
      { file: "src/lib/vstudio/labels.ts", name: "LABEL_RU", prefix: "" },
      { file: "src/lib/vstudio/errors.ts", name: "BLOCKING_RU", prefix: "errors." },
      { file: "src/lib/vstudio/errors.ts", name: "HTTP_RU", prefix: "errors." },
      { file: "src/lib/vstudio/errors.ts", name: "TAKE_ERROR_RU", prefix: "errors." },
      { file: "src/lib/vstudio/errors.ts", name: "CLIENT_RU", prefix: "errors." },
      { file: "src/lib/vstudio/errors.ts", name: "WARNING_RU", prefix: "warnings." },
      // issueText передаёт кадрам context "frame" → ключ errors.<code>_frame.
      { file: "src/lib/vstudio/errors.ts", name: "FRAME_RU", prefix: "errors.", suffix: "_frame" },
      { file: "src/lib/vstudio/errors.ts", name: "FIELD_RU", prefix: "fields." },
      { file: "src/lib/vstudio/errors.ts", name: "SUBJECT_RU", prefix: "subject." },
      { file: "src/components/vstudio/feed/CompiledDisclosure.tsx", name: "MODE_RU", prefix: "sent.mode." },
    ],
    // Списки объектов с русскими полями: VS_EXAMPLES → empty.examples.<id>.<поле>,
    // VS_TEMPLATES (сценарии первого экрана) → home.tpl.<id>.<поле>.
    lists: [
      {
        file: "src/components/vstudio/feed/examples.ts",
        name: "VS_EXAMPLES",
        id: "id",
        fields: { title: "empty.examples.{id}.title", prompt: "empty.examples.{id}.prompt" },
      },
      {
        file: "src/components/vstudio/home/templates.ts",
        name: "VS_TEMPLATES",
        id: "id",
        fields: { label: "home.tpl.{id}.label", prompt: "home.tpl.{id}.prompt" },
      },
    ],
    // Ключи, которые код собирает шаблоном (`errors.${code}`). Под этими
    // префиксами в ru бывают и коды одного бэкенда — их не зовём «лишними».
    dynamic: ["errors.", "warnings.", "subject.", "fields.", "sent.mode.", "empty.examples.", "home.tpl.", "library.filter."],
  },
  // EsAI Creators. Только папки программы: в них t() без ns — ключ creators.
  // Nav, Footer, сайдбар чата, профиль и поле промокода зовут creators через
  // ns: "creators" и берут тексты из таблиц ниже, а их t() без ns — common/home.
  creators: {
    dirs: ["src/app/creators", "src/components/creators", "src/lib/creators"],
    tables: [
      { file: "src/lib/creators/errors.ts", name: "ERROR_RU", prefix: "errors." },
      { file: "src/lib/creators/errors.ts", name: "PROMO_ERROR_RU", prefix: "promo.errors." },
      { file: "src/lib/creators/labels.ts", name: "APPLICATION_STATUS_RU", prefix: "status.application." },
      { file: "src/lib/creators/labels.ts", name: "PUBLICATION_STATUS_RU", prefix: "status.publication." },
      { file: "src/lib/creators/labels.ts", name: "WITHDRAWAL_STATUS_RU", prefix: "status.withdrawal." },
      { file: "src/lib/creators/labels.ts", name: "COMMISSION_STATUS_RU", prefix: "status.commission." },
      { file: "src/lib/creators/labels.ts", name: "NETWORK_RU", prefix: "network." },
      { file: "src/lib/creators/labels.ts", name: "SOURCE_RU", prefix: "source." },
      { file: "src/lib/creators/labels.ts", name: "CREDIT_CATEGORY_RU", prefix: "credits.category." },
      { file: "src/lib/creators/labels.ts", name: "NAV_RU", prefix: "nav." },
    ],
    dynamic: ["errors.", "promo.errors.", "status.", "network.", "source.", "credits.category.", "nav."],
  },
};

/** Похоже на ключ перевода: «group.key» и глубже, без пробелов. */
const KEY_RE = /^(?:[a-z][a-z0-9_]*:)?[a-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$/;
const DYNAMIC_HEAD_RE = /^[a-z][A-Za-z0-9_]*\.(?:[A-Za-z0-9_]+\.)*$/;
/** Функции перевода студии: t, обёртки ct/tx/tr, t из ref (tRef.current). */
const TRANSLATE_CALLEE_RE = /^(?:t|tt|tr|tx|ct|fn|translate|i18n\.t|i18next\.t|\w+Ref\.current)$/;
const OPTION_NAMES = new Set(["defaultValue", "ns", "count", "context"]);

function loadTypeScript(root) {
  try {
    return createRequire(path.join(root, "package.json"))("typescript");
  } catch {
    return null;
  }
}

function walkSources(dir, out = []) {
  if (!fs.existsSync(dir)) return out;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walkSources(p, out);
    else if (/\.(ts|tsx)$/.test(e.name) && !/\.d\.ts$/.test(e.name)) out.push(p);
  }
  return out;
}

const relPath = (root, file) => path.relative(root, file).split(path.sep).join("/");

/**
 * Разобрать исходники: ключи в вызовах, таблицы *_RU, объекты {key, ru},
 * шаблонные ключи. Возвращает сырой материал — решает scanCode.
 */
export function extractFromSources(ts, sources) {
  const calls = [];
  const phrases = [];
  const templates = [];
  const loose = [];
  const tables = new Map(); // "file#NAME" → [[key, value]]
  const lists = new Map(); // "file#NAME" → [{prop: value}]

  const isStr = (n) => n && (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n));
  const unwrap = (n) => {
    while (n && (ts.isParenthesizedExpression(n) || ts.isAsExpression(n) || ts.isTypeAssertionExpression(n) || ts.isSatisfiesExpression?.(n) || ts.isNonNullExpression(n))) n = n.expression;
    return n;
  };
  const propName = (p) => (p.name && (ts.isIdentifier(p.name) || ts.isStringLiteral(p.name) || ts.isNumericLiteral(p.name)) ? p.name.text : null);
  const objStrings = (obj) => {
    const out = {};
    for (const p of obj.properties) {
      if (!ts.isPropertyAssignment(p)) continue;
      const name = propName(p);
      const init = unwrap(p.initializer);
      if (name != null && isStr(init)) out[name] = init.text;
    }
    return out;
  };

  for (const { file, text } of sources) {
    const kind = file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
    const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
    const at = (node) => `${file}:${sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1}`;

    // Вызов, в аргументы которого (через ?:, скобки, as) попала строка.
    const callFor = (node) => {
      let cur = node;
      for (;;) {
        const p = cur.parent;
        if (!p) return null;
        if (ts.isCallExpression(p) && p.arguments.includes(cur)) return { call: p, arg: cur };
        if (ts.isParenthesizedExpression(p) || ts.isAsExpression(p) || ts.isTypeAssertionExpression(p) || ts.isNonNullExpression(p)) {
          cur = p;
          continue;
        }
        if (ts.isConditionalExpression(p) && (p.whenTrue === cur || p.whenFalse === cur)) {
          cur = p;
          continue;
        }
        if (ts.isBinaryExpression(p) && (p.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken || p.operatorToken.kind === ts.SyntaxKind.BarBarToken)) {
          cur = p;
          continue;
        }
        return null;
      }
    };

    const visit = (node) => {
      // const NAME = { … } / [ {…}, … ] — таблицы и списки.
      if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
        const init = unwrap(node.initializer);
        const id = `${file}#${node.name.text}`;
        if (ts.isObjectLiteralExpression(init)) {
          const rows = [];
          for (const p of init.properties) {
            if (!ts.isPropertyAssignment(p)) continue;
            const name = propName(p);
            const v = unwrap(p.initializer);
            if (name != null && isStr(v)) rows.push([name, v.text]);
          }
          tables.set(id, rows);
        } else if (ts.isArrayLiteralExpression(init)) {
          const rows = init.elements.map(unwrap).filter((e) => e && ts.isObjectLiteralExpression(e)).map(objStrings);
          lists.set(id, rows);
        }
      }

      if (ts.isTemplateExpression(node) && DYNAMIC_HEAD_RE.test(node.head.text)) {
        templates.push({ head: node.head.text, at: at(node) });
      }

      if (isStr(node) && KEY_RE.test(node.text)) {
        const parent = node.parent;
        if (ts.isPropertyAssignment(parent) && parent.name === node) {
          // ключ таблицы — его заберёт разбор таблицы
        } else if (ts.isPropertyAssignment(parent) && parent.initializer === node && propName(parent) === "key") {
          const sib = objStrings(parent.parent);
          phrases.push({ key: node.text, ru: sib.ru ?? null, at: at(node) });
        } else {
          const hit = callFor(node);
          let call = null;
          if (hit) {
            const { arg } = hit;
            call = hit.call;
            const i = call.arguments.indexOf(arg);
            let def = null;
            let plural = false;
            let context = null;
            let ns = null;
            let hasOptions = false;
            const next = unwrap(call.arguments[i + 1]);
            if (isStr(next)) def = next.text;
            for (const a of call.arguments.slice(i + 1).map(unwrap)) {
              if (!a || !ts.isObjectLiteralExpression(a)) continue;
              for (const p of a.properties) {
                const name = p.name && ts.isIdentifier(p.name) ? p.name.text : propName(p);
                if (OPTION_NAMES.has(name)) hasOptions = true;
                if (name === "count") plural = true;
                if (!ts.isPropertyAssignment(p)) continue;
                const v = unwrap(p.initializer);
                if (name === "defaultValue" && isStr(v)) def = v.text;
                if (name === "context" && isStr(v)) context = v.text;
                if (name === "ns" && isStr(v)) ns = v.text;
              }
            }
            const callee = call.expression.getText(sf);
            const first = call.arguments[0];
            // Перевод, а не любой вызов со строкой «a.b» (querySelector("div.x")):
            // функция перевода, обёртка ct(t, …), опции i18next или русский вторым аргументом.
            const translating =
              TRANSLATE_CALLEE_RE.test(callee) ||
              (first && ts.isIdentifier(first) && /^(t|tt|tr)$/.test(first.text)) ||
              hasOptions ||
              def != null;
            if (translating) calls.push({ key: node.text, def, plural, context, ns, callee, at: at(node) });
            else call = null;
          }
          if (!call) loose.push({ key: node.text, at: at(node) });
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }
  return { calls, phrases, templates, loose, tables, lists };
}

/**
 * Что код ждёт от ru: Map ключ → {defaults:Set, plural, sites:[]}, плюс
 * шаблонные префиксы и ошибки конфигурации (пропала таблица).
 */
export function expectedFromCode(extracted, config, ns) {
  const expected = new Map();
  const errors = [];
  const add = (key, def, site, extra = {}) => {
    if (!expected.has(key)) expected.set(key, { defaults: new Set(), plural: false, sites: [] });
    const e = expected.get(key);
    if (def != null) e.defaults.add(def);
    if (extra.plural) e.plural = true;
    e.sites.push(site);
  };
  const stripNs = (key) => {
    const m = /^([a-z][a-z0-9_]*):(.+)$/.exec(key);
    return m ? { ns: m[1], key: m[2] } : { ns: null, key };
  };

  for (const c of extracted.calls) {
    const { ns: prefixNs, key } = stripNs(c.key);
    const callNs = c.ns || prefixNs;
    if (callNs && callNs !== ns) continue;
    const full = c.context ? `${key}_${c.context}` : key;
    add(full, c.def, `${c.at} ${c.callee}()`, { plural: c.plural });
  }
  for (const p of extracted.phrases) add(stripNs(p.key).key, p.ru, `${p.at} {key, ru}`);

  for (const tb of config.tables || []) {
    const rows = extracted.tables.get(`${tb.file}#${tb.name}`);
    if (!rows) {
      errors.push(`код: не найдена таблица ${tb.name} в ${tb.file} — обновите CODE_SCAN в scripts/i18n-parity.mjs`);
      continue;
    }
    for (const [k, v] of rows) {
      // Пустой текст — «не показывать» (errors.aborted), переводить нечего.
      if (!v) continue;
      add(`${tb.prefix || ""}${k}${tb.suffix || ""}`, v, `${tb.file} ${tb.name}.${k}`);
    }
  }
  for (const ls of config.lists || []) {
    const rows = extracted.lists.get(`${ls.file}#${ls.name}`);
    if (!rows) {
      errors.push(`код: не найден список ${ls.name} в ${ls.file} — обновите CODE_SCAN в scripts/i18n-parity.mjs`);
      continue;
    }
    for (const row of rows) {
      const id = row[ls.id];
      if (!id) continue;
      for (const [field, pattern] of Object.entries(ls.fields)) {
        if (row[field]) add(pattern.replace("{id}", id), row[field], `${ls.file} ${ls.name}[${id}].${field}`);
      }
    }
  }
  const dynamic = new Set(config.dynamic || []);
  const uncovered = [...new Map(extracted.templates.filter((t) => ![...dynamic].some((d) => t.head.startsWith(d))).map((t) => [t.head, t])).values()];
  return { expected, dynamic, uncovered, errors };
}

/** Сверка ru с ожиданиями кода. */
export function compareWithCode(ref, code, { verbose = false, loose = [] } = {}) {
  const errors = [...code.errors];
  const warnings = [];
  const families = pluralFamilies(ref);
  const refCats = pluralCategories(REFERENCE);
  const used = new Set();

  for (const [key, e] of code.expected) {
    const site = e.sites[0];
    if (e.plural) {
      used.add(key);
      for (const c of refCats) {
        used.add(`${key}_${c}`);
        if (!ref.has(`${key}_${c}`)) errors.push(`ru: нет формы «${key}_${c}» (count в ${site})`);
      }
      continue;
    }
    used.add(key);
    if (!ref.has(key)) {
      errors.push(`ru: нет ключа «${key}» — ${site}`);
      continue;
    }
    if (e.defaults.size > 1) {
      warnings.push(`код: у «${key}» разные русские тексты в разных местах: ${[...e.defaults].map((d) => `«${d}»`).join(" / ")}`);
    }
    if (e.defaults.size && !e.defaults.has(ref.get(key))) {
      errors.push(`ru: «${key}» = «${ref.get(key)}», а в коде «${[...e.defaults][0]}» — ${site}`);
    }
  }

  for (const t of code.uncovered) {
    warnings.push(`код: шаблонный ключ «${t.head}…» (${t.at}) не описан в CODE_SCAN.dynamic — его ключи не проверены`);
  }

  // Строки кода, похожие на ключ (карты вида {upload: "library.source.upload"}).
  for (const l of loose) if (ref.has(l.key)) used.add(l.key);

  const unused = [];
  for (const key of ref.keys()) {
    if (used.has(key)) continue;
    const m = PLURAL_RE.exec(key);
    if (m && families.has(m[1]) && used.has(m[1])) continue;
    if ([...code.dynamic].some((d) => key.startsWith(d))) continue;
    unused.push(key);
  }
  if (unused.length) warnings.push(`ru: ключи, которых не видно в коде (${unused.length}): ${unused.join(", ")}`);
  if (verbose) {
    const unknown = loose.filter((l) => !ref.has(l.key));
    for (const l of unknown) warnings.push(`код: строка «${l.key}» похожа на ключ, но её нет в ru — ${l.at}`);
  }
  return { errors, warnings };
}

export function scanCode(root, ns, config = CODE_SCAN[ns]) {
  const ts = loadTypeScript(root);
  if (!ts) return null;
  const sources = config.dirs
    .flatMap((d) => walkSources(path.join(root, d)))
    .map((file) => ({ file: relPath(root, file), text: fs.readFileSync(file, "utf8") }));
  const extracted = extractFromSources(ts, sources);
  return { extracted, code: expectedFromCode(extracted, config, ns), files: sources.length };
}

/* ------------------------------------------------------------------ */
/* Прогон                                                              */
/* ------------------------------------------------------------------ */

export function checkNamespace(root, ns, { code = true, verbose = false } = {}) {
  const errors = [];
  const warnings = [];
  const info = [];
  const ref = loadLocale(root, REFERENCE, ns);
  if (ref.missing) return { errors: [`${REFERENCE}: нет файла ${ref.file}`], warnings, info };
  errors.push(...ref.problems.map((p) => `${REFERENCE}: ${p}`));
  errors.push(...checkReference(ref.keys));

  for (const lang of LANGS) {
    if (lang === REFERENCE) continue;
    const loc = loadLocale(root, lang, ns);
    if (loc.missing) {
      errors.push(`${lang}: нет файла ${relPath(root, loc.file)}`);
      continue;
    }
    errors.push(...loc.problems.map((p) => `${lang}: ${p}`));
    const res = comparePair(ref.keys, loc.keys, lang);
    errors.push(...res.errors);
    warnings.push(...res.warnings);
  }

  if (code && CODE_SCAN[ns]) {
    const scan = scanCode(root, ns);
    if (!scan) {
      warnings.push("код: нет пакета typescript — сверка с кодом пропущена");
    } else {
      const res = compareWithCode(ref.keys, scan.code, { verbose, loose: scan.extracted.loose });
      errors.push(...res.errors);
      warnings.push(...res.warnings);
      info.push(`код: ${scan.files} файлов, ${scan.code.expected.size} ключей со строкой в коде`);
    }
  }
  info.push(`${ref.keys.size} ключей в ${REFERENCE}`);
  return { errors, warnings, info };
}

/** Отставание en/kg от ru для нестрогих namespace — без падения. */
export function lagReport(root, ns) {
  const ref = loadLocale(root, REFERENCE, ns);
  const lines = [];
  for (const lang of LANGS) {
    if (lang === REFERENCE) continue;
    const loc = loadLocale(root, lang, ns);
    if (loc.missing) {
      lines.push(`${lang}: нет файла`);
      continue;
    }
    const res = comparePair(ref.keys, loc.keys, lang);
    const isMissing = (e) => /: нет (ключа|формы) «/.test(e);
    const missing = res.errors.filter(isMissing).map((e) => e.replace(/^.*?«(.+)»$/, "$1"));
    const other = res.errors.filter((e) => !isMissing(e));
    if (!missing.length && !other.length) continue;
    const parts = [];
    if (missing.length) parts.push(`не хватает ${missing.length}: ${missing.slice(0, 12).join(", ")}${missing.length > 12 ? ", …" : ""}`);
    if (other.length) parts.push(`прочих расхождений ${other.length}, например: ${other[0].replace(/^\w+: /, "")}`);
    lines.push(`${lang}: ${parts.join("; ")}`);
  }
  return lines;
}

export function main(argv = process.argv.slice(2), root = NEXT_ROOT, log = console.log) {
  const flags = new Set(argv.filter((a) => a.startsWith("--")));
  const strict = argv.filter((a) => !a.startsWith("--"));
  const all = listNamespaces(root);
  const verbose = flags.has("--verbose");
  let failed = 0;

  for (const ns of strict) {
    const { errors, warnings, info } = checkNamespace(root, ns, { code: !flags.has("--no-code"), verbose });
    log(`\n[${ns}] ${errors.length ? `ОШИБОК: ${errors.length}` : "ок"} · ${info.join(" · ")}`);
    for (const e of errors) log(`  ✗ ${e}`);
    for (const w of warnings) log(`  ! ${w}`);
    if (errors.length) failed += 1;
  }

  // Остальные namespace — только отчёт (например, отставание en в common.json).
  const rest = all.filter((ns) => !strict.includes(ns));
  const lagLines = [];
  for (const ns of rest) {
    const lines = lagReport(root, ns);
    if (!lines.length) lagLines.push(`  · ${ns}.json: en и kg в паритете с ru`);
    for (const line of lines) lagLines.push(`  · ${ns}.json ${line}`);
  }
  if (lagLines.length) {
    log(`\nНестрогие namespace (не роняют проверку):`);
    for (const l of lagLines) log(l);
  }
  if (!strict.length) log("\nСтрогие namespace не заданы: node scripts/i18n-parity.mjs vstudio");
  log(failed ? `\nПаритет нарушен в ${failed} namespace.` : "\nПаритет в порядке.");
  return failed ? 1 : 0;
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) process.exitCode = main();
