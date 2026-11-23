// Админка, «Creative Studio»: разбор ответов, превью наценки, строки журнала, период (creativeAdmin.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/app/admin-new/creative/creativeAdmin.test.mjs
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";

const ca = await import("./creativeAdmin.ts");

// Ответ GET manage/creative/settings/ в форме views_manage.settings_payload.
const SETTINGS = {
  mode: "staff",
  mode_env: "staff",
  mode_override: null,
  markup_pct: "40",
  markup_default_pct: "40",
  floor_pct: "25",
  credit_usd: "0.008780",
  tools: [
    {
      id: "text-to-image", n: 8, name: "Создание по описанию", kind: "image", enabled: true,
      own_markup_pct: null, use_own_markup: false, effective_markup_pct: "40", uses_global: true,
      example: { label: "720p, 1 шт.", cost_usd: "0.0040", credits: 1 },
    },
    {
      id: "motion-transfer", n: 1, name: "Перенос движения", kind: "video", enabled: false,
      own_markup_pct: "55", use_own_markup: true, effective_markup_pct: "55", uses_global: false,
      example: { label: "5 с, 480p", cost_usd: "0.7700", credits: 123 },
    },
    {
      id: "portrait", n: 11, name: "Фотореалистичный портрет", kind: "image", enabled: true,
      own_markup_pct: "10", use_own_markup: true, effective_markup_pct: "25", uses_global: false,
      example: { label: "720p", cost_usd: "0.0940", credits: 14 },
    },
    { id: "", name: "мусор" },
    "строка",
  ],
};

test("parseSettings: ответ сервера → страница; порядок по номеру карточки; мусор не роняет", () => {
  const s = ca.parseSettings(SETTINGS);
  assert.ok(s);
  assert.equal(s.mode, "staff");
  assert.equal(s.modeOverride, null);
  assert.equal(s.canEditMoney, null);
  assert.deepEqual(s.tools.map((t) => t.id), ["motion-transfer", "text-to-image", "portrait"]);
  const mt = s.tools[0];
  assert.equal(mt.enabled, false);
  assert.equal(mt.useOwnMarkup, true);
  assert.equal(mt.usesGlobal, false);
  assert.deepEqual(mt.example, { label: "5 с, 480p", costUsd: "0.7700", credits: 123 });
  assert.equal(ca.parseSettings(null), null);
  assert.equal(ca.parseSettings({ mode: "maybe", markup_pct: "40" }), null);
  assert.equal(ca.parseSettings({ mode: "on" }), null);
  assert.equal(ca.parseSettings({ ...SETTINGS, can_edit_money: false }).canEditMoney, false);
});

test("estimateCredits: формула сервера с порогом и минимумом 1 кр", () => {
  // 0.77 × 1.4 / 0.00878 = 122.77… → 123
  assert.equal(ca.estimateCredits("0.77", 40, "25", "0.00878"), 123);
  // наценка ниже порога — считаем по порогу: 0.77 × 1.25 / 0.00878 = 109.6… → 110
  assert.equal(ca.estimateCredits("0.77", 10, "25", "0.00878"), 110);
  assert.equal(ca.estimateCredits("0.0001", 40, "25", "0.00878"), 1);
  // ровно целое не округляется вверх из-за дробей: 0.1 × 1.5 / 0.01 = 15
  assert.equal(ca.estimateCredits("0.1", 50, "0", "0.01"), 15);
  assert.equal(ca.estimateCredits(null, 40, "25", "0.00878"), null);
  assert.equal(ca.estimateCredits("0.77", 40, "25", null), null);
  assert.equal(ca.estimateCredits("0.77", 40, "25", "0"), null);
});

test("previewRows: своя наценка не меняется, тот же процент — цена сервера", () => {
  const s = ca.parseSettings(SETTINGS);
  const same = ca.previewRows(s, 40);
  assert.deepEqual(same.map((r) => r.next), same.map((r) => r.now));
  assert.equal(ca.changedPreview(same).length, 0);
  const more = ca.previewRows(s, 100);
  const byId = Object.fromEntries(more.map((r) => [r.id, r]));
  assert.equal(byId["motion-transfer"].next, 123);
  assert.equal(byId["motion-transfer"].own, true);
  assert.equal(byId["portrait"].next, 14);
  // 0.004 × 2 / 0.00878 = 0.91 → минимум 1: не изменилось
  assert.equal(byId["text-to-image"].next, 1);
  assert.equal(ca.changedPreview(more).length, 0);
});

test("markupChange: проверка поля и сравнение чисел", () => {
  const s = ca.parseSettings(SETTINGS);
  assert.deepEqual(ca.markupChange("40,00", s), { body: null, error: null });
  assert.deepEqual(ca.markupChange("45,5", s), { body: { markup_pct: "45.5" }, error: null });
  assert.match(ca.markupChange("", s).error, /число/);
  assert.match(ca.markupChange("1001", s).error, /до 1000/);
  assert.match(ca.markupChange("12,345", s).error, /2 знаков/);
  assert.match(ca.markupChange("-5", s).error, /число/);
});

test("ownChange: пусто — снова общая, число — своя, без изменений — ничего", () => {
  const s = ca.parseSettings(SETTINGS);
  const [mt, t2i] = s.tools;
  assert.equal(ca.ownDraft(mt), "55");
  assert.equal(ca.ownDraft(t2i), "");
  assert.deepEqual(ca.ownChange(mt, "55,0"), { item: null, error: null });
  assert.deepEqual(ca.ownChange(mt, " "), {
    item: { id: "motion-transfer", use_own_markup: false, markup_pct: null },
    error: null,
  });
  assert.deepEqual(ca.ownChange(t2i, ""), { item: null, error: null });
  assert.deepEqual(ca.ownChange(t2i, "60"), {
    item: { id: "text-to-image", use_own_markup: true, markup_pct: "60" },
    error: null,
  });
  assert.match(ca.ownChange(t2i, "abc").error, /Своя наценка/);
});

test("markupSource: общая, своя, порог", () => {
  const s = ca.parseSettings(SETTINGS);
  const [mt, t2i, portrait] = s.tools;
  assert.deepEqual(ca.markupSource(t2i, s), { pct: "40", source: "global" });
  assert.deepEqual(ca.markupSource(mt, s), { pct: "55", source: "own" });
  assert.deepEqual(ca.markupSource(portrait, s), { pct: "25", source: "floor" });
});

test("logLines: наши слова вместо ключей сервера", () => {
  const lines = ca.logLines(
    {
      at: "2026-11-23T10:00:00+06:00",
      actor: "a@b.c",
      before: { mode: null, markup_pct: null, "tool:portrait": { enabled: true, markup_pct: null, use_own_markup: false } },
      after: { mode: "on", markup_pct: "45", "tool:portrait": { enabled: false, markup_pct: "30", use_own_markup: true } },
    },
    { names: { portrait: "Портрет" }, defaultPct: "40" },
  );
  assert.deepEqual(lines, [
    { label: "Режим", before: "как в окружении", after: "Открыт всем" },
    { label: "Общая наценка", before: "по умолчанию (40 %)", after: "45 %" },
    { label: "Портрет", before: "включён", after: "выключен" },
    { label: "Портрет: наценка", before: "общая", after: "30 %" },
  ]);
  assert.equal(ca.parseLog({ items: [{ at: "", actor: "x" }, { at: "2026-11-23", actor: "y", before: 1 }] }).length, 1);
  assert.equal(ca.parseLog({}), null);
});

test("parseSummary и деньги", () => {
  const s = ca.parseSummary({
    from: "2026-10-25", to: "2026-11-23",
    jobs: { total: 10, done: 7, failed: 1, nsfw: 0, canceled: 1, lost: 0, open: 1 },
    credits_charged: 700, credit_usd: "0.008780",
    revenue_usd: "6.15", cost_usd: "3.2000", margin_usd: "2.95",
    by_tool: [{ id: "portrait", name: "Портрет", jobs: 3, done: 2, credits: 28, revenue_usd: null, cost_usd: "0.1880", margin_usd: null }, { name: "x" }],
  });
  assert.ok(s);
  assert.equal(s.jobs.done, 7);
  assert.equal(s.byTool.length, 1);
  assert.equal(ca.marginShare(s), "48 %");
  assert.equal(ca.marginShare(s.byTool[0]), null);
  assert.equal(ca.parseSummary({ from: "a" }), null);
  assert.equal(ca.usdText("3.2000"), "$3,20");
  assert.equal(ca.usdText("0.0390"), "$0,039");
  assert.equal(ca.usdText("-1.5"), "−$1,50");
  assert.equal(ca.usdText(null), "—");
});

test("период: последние N дней, свой период, подпись", () => {
  assert.deepEqual(ca.periodRange(30, new Date(2026, 10, 23)), { from: "2026-10-25", to: "2026-11-23" });
  assert.deepEqual(ca.periodRange(7, new Date(2026, 0, 3)), { from: "2025-12-28", to: "2026-01-03" });
  assert.equal(ca.rangeProblem("2026-11-01", "2026-11-23"), null);
  assert.match(ca.rangeProblem("2026-11-24", "2026-11-23"), /позже/);
  assert.match(ca.rangeProblem("2024-01-01", "2026-11-23"), /года/);
  assert.match(ca.rangeProblem("2026-02-30", "2026-11-23"), /обе даты/);
  assert.equal(ca.rangeText("2026-11-01", "2026-11-23"), "01.11 — 23.11.2026");
  assert.equal(ca.rangeText("2025-12-28", "2026-01-03"), "28.12.2025 — 03.01.2026");
  assert.equal(ca.summaryPath("2026-11-01", "2026-11-23"), "manage/creative/summary/?from=2026-11-01&to=2026-11-23");
});

test("errorText: связь, роль, отказ сервера с полем", () => {
  assert.match(ca.errorText({ status: 0 }, "x"), /Нет связи/);
  assert.equal(ca.errorText({ status: 403, data: { detail: "…", code: "superuser_required" } }, "x"), ca.SUPERUSER_TEXT);
  assert.equal(ca.isSuperuserRefusal({ status: 403, data: { code: "superuser_required" } }), true);
  assert.equal(ca.isSuperuserRefusal({ status: 403, data: {} }), false);
  assert.equal(
    ca.errorText({ status: 400, data: { detail: "Проверьте поля.", errors: { markup_pct: "Наценка — число от 0 до 1000." } } }, "x"),
    "Проверьте поля. Наценка — число от 0 до 1000.",
  );
  assert.equal(ca.errorText({ status: 500, data: "<html>" }, "Не удалось"), "Не удалось (HTTP 500)");
});

test("в коде страницы нет имён поставщика и его моделей (админский JS публичен)", () => {
  const banned = /higgsfield|soul|genjutsu|cinema studio|marketing studio|flare|sunburst|ads studio|ai influencer|gpt image/i;
  const files = readdirSync(new URL("./", import.meta.url)).filter((f) => /\.tsx?$/.test(f));
  assert.ok(files.includes("page.tsx"));
  for (const file of files) {
    const src = readFileSync(new URL(`./${file}`, import.meta.url), "utf8");
    assert.equal(banned.exec(src)?.[0] ?? null, null, file);
  }
});
