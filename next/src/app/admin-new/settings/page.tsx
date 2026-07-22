"use client";

import { useEffect, useState } from "react";
import { fetchData } from "@/tools/fetchData";
import {
  FiKey,
  FiGift,
  FiImage,
  FiPhone,
  FiEye,
  FiEyeOff,
  FiCheck,
  FiDollarSign,
} from "react-icons/fi";

type SiteContacts = {
  email: string;
  phone: string;
  address: string;
  telegram: string;
  instagram: string;
  facebook: string;
  twitter: string;
};

type Settings = {
  openrouter_key_masked: string | null;
  welcome_bonus: number;
  referral_bonus: number;
  referral_percent: number;
  daily_retention_target: number;
  web_search_surcharge: number;
  free_daily_requests: number;
  paid_daily_requests: number;
  image_auto_route: boolean;
  currency_kgs_to_rub_rate: number;
  site: SiteContacts;
};

type TestResult = {
  ok: boolean;
  balance_usd: number | null;
  error: string | null;
};

const INPUT =
  "rounded-lg bg-surface-2 border border-border px-3 py-2 text-sm text-foreground focus:border-accent outline-none";

type NumKey =
  | "welcome_bonus"
  | "referral_bonus"
  | "referral_percent"
  | "daily_retention_target"
  | "web_search_surcharge"
  | "free_daily_requests"
  | "paid_daily_requests";

const NUM_FIELDS: { key: NumKey; label: string; sub: string; max?: number }[] = [
  {
    key: "welcome_bonus",
    label: "Приветственный бонус (кр)",
    sub: "начисляется новому пользователю при регистрации",
  },
  {
    key: "referral_bonus",
    label: "Реферальный бонус (кр)",
    sub: "за приглашённого друга по реферальной ссылке",
  },
  {
    key: "referral_percent",
    label: "Реферальный % с пополнений",
    sub: "процент от пополнений приглашённого начисляется пригласившему (0..100)",
    max: 100,
  },
  {
    key: "daily_retention_target",
    label: "Ежедневный бонус до (кр)",
    sub: "добивка баланса до этой суммы за ежедневный вход",
  },
  {
    key: "web_search_surcharge",
    label: "Надбавка за веб-поиск (кр)",
    sub: "дополнительно к цене запроса с поиском в интернете",
  },
  {
    key: "free_daily_requests",
    label: "Лимит запросов/день бесплатным",
    sub: "максимум запросов в сутки без платного пакета",
  },
  {
    key: "paid_daily_requests",
    label: "Лимит запросов/день платным",
    sub: "максимум запросов в сутки после покупки пакета",
  },
];

const SITE_FIELDS: { key: keyof SiteContacts; label: string; placeholder: string }[] = [
  { key: "email", label: "Email", placeholder: "info@esai.kg" },
  { key: "phone", label: "Телефон", placeholder: "+996 ..." },
  { key: "address", label: "Адрес", placeholder: "Бишкек, ..." },
  { key: "telegram", label: "Telegram", placeholder: "https://t.me/..." },
  { key: "instagram", label: "Instagram", placeholder: "https://instagram.com/..." },
  { key: "facebook", label: "Facebook", placeholder: "https://facebook.com/..." },
  { key: "twitter", label: "Twitter / X", placeholder: "https://x.com/..." },
];

function SavedFlash() {
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-400">
      <FiCheck className="h-4 w-4" /> Сохранено
    </span>
  );
}

export default function AdminSettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // --- Секция 1: ключ OpenRouter ---
  const [newKey, setNewKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [keySaving, setKeySaving] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);
  const [keyFlash, setKeyFlash] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

  // --- Секции 2–3: числа и авто-рисование (черновики) ---
  const [numDraft, setNumDraft] = useState<Record<NumKey, string>>({
    welcome_bonus: "",
    referral_bonus: "",
    referral_percent: "",
    daily_retention_target: "",
    web_search_surcharge: "",
    free_daily_requests: "",
    paid_daily_requests: "",
  });
  const [imageAutoRoute, setImageAutoRoute] = useState(false);
  const [bonusSaving, setBonusSaving] = useState(false);
  const [bonusError, setBonusError] = useState<string | null>(null);
  const [bonusFlash, setBonusFlash] = useState(false);

  // --- Секция: курс KGS -> RUB (переключатель валют на /pricing) ---
  const [rateDraft, setRateDraft] = useState("");
  const [rateSaving, setRateSaving] = useState(false);
  const [rateError, setRateError] = useState<string | null>(null);
  const [rateFlash, setRateFlash] = useState(false);

  // --- Секция 4: контакты сайта ---
  const [siteDraft, setSiteDraft] = useState<SiteContacts>({
    email: "",
    phone: "",
    address: "",
    telegram: "",
    instagram: "",
    facebook: "",
    twitter: "",
  });
  const [siteSaving, setSiteSaving] = useState(false);
  const [siteError, setSiteError] = useState<string | null>(null);
  const [siteFlash, setSiteFlash] = useState(false);

  const applySnapshot = (s: Settings) => {
    setSettings(s);
    setNumDraft({
      welcome_bonus: String(s.welcome_bonus ?? 0),
      referral_bonus: String(s.referral_bonus ?? 0),
      referral_percent: String(s.referral_percent ?? 0),
      daily_retention_target: String(s.daily_retention_target ?? 0),
      web_search_surcharge: String(s.web_search_surcharge ?? 0),
      free_daily_requests: String(s.free_daily_requests ?? 0),
      paid_daily_requests: String(s.paid_daily_requests ?? 0),
    });
    setImageAutoRoute(Boolean(s.image_auto_route));
    setRateDraft(String(s.currency_kgs_to_rub_rate ?? ""));
    setSiteDraft({
      email: s.site?.email ?? "",
      phone: s.site?.phone ?? "",
      address: s.site?.address ?? "",
      telegram: s.site?.telegram ?? "",
      instagram: s.site?.instagram ?? "",
      facebook: s.site?.facebook ?? "",
      twitter: s.site?.twitter ?? "",
    });
  };

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<Settings>("manage/settings/", "GET", null, true);
      if (!alive) return;
      if (res.ok && res.data) applySnapshot(res.data);
      else setError(res.error || "Не удалось загрузить настройки");
      setLoading(false);
    })();
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------- Ключ OpenRouter ----------

  const runTest = async (key?: string) => {
    setTesting(true);
    setTestResult(null);
    const res = await fetchData<TestResult>(
      "manage/settings/test-openrouter/",
      "POST",
      key ? { key } : {},
      true
    );
    setTesting(false);
    if (res.ok && res.data) setTestResult(res.data);
    else
      setTestResult({
        ok: false,
        balance_usd: null,
        error: res.error || "Не удалось проверить ключ",
      });
  };

  const replaceKey = async () => {
    const key = newKey.trim();
    if (!key) return;
    if (
      !confirm(
        "Заменить ключ OpenRouter? С нерабочим ключом чат перестанет отвечать всем пользователям."
      )
    )
      return;
    setKeySaving(true);
    setKeyError(null);
    const res = await fetchData<Settings>(
      "manage/settings/",
      "PATCH",
      { openrouter_key: key },
      true
    );
    setKeySaving(false);
    if (res.ok && res.data) {
      applySnapshot(res.data);
      setNewKey("");
      setShowKey(false);
      setKeyFlash(true);
      setTimeout(() => setKeyFlash(false), 2000);
      // Сразу проверяем новый (теперь действующий) ключ
      void runTest();
    } else {
      setKeyError(res.error || "Не удалось заменить ключ");
    }
  };

  // ---------- Бонусы, лимиты, авто-рисование ----------

  const parseNum = (v: string, max?: number): number | null => {
    if (v.trim() === "") return null;
    const n = Number(v);
    if (!Number.isFinite(n) || !Number.isInteger(n) || n < 0) return null;
    if (typeof max === "number" && n > max) return null;
    return n;
  };

  const bonusDirty =
    settings !== null &&
    (NUM_FIELDS.some((f) => parseNum(numDraft[f.key], f.max) !== settings[f.key]) ||
      imageAutoRoute !== settings.image_auto_route);

  const saveBonuses = async () => {
    if (!settings) return;
    const patch: Record<string, number | boolean> = {};
    for (const f of NUM_FIELDS) {
      const n = parseNum(numDraft[f.key], f.max);
      if (n === null) {
        setBonusError(
          typeof f.max === "number"
            ? `«${f.label}» — введите целое число от 0 до ${f.max}`
            : `«${f.label}» — введите целое число не меньше 0`
        );
        return;
      }
      if (n !== settings[f.key]) patch[f.key] = n;
    }
    if (imageAutoRoute !== settings.image_auto_route) patch.image_auto_route = imageAutoRoute;
    if (Object.keys(patch).length === 0) return;
    setBonusSaving(true);
    setBonusError(null);
    const res = await fetchData<Settings>("manage/settings/", "PATCH", patch, true);
    setBonusSaving(false);
    if (res.ok && res.data) {
      applySnapshot(res.data);
      setBonusFlash(true);
      setTimeout(() => setBonusFlash(false), 2000);
    } else {
      setBonusError(res.error || "Не удалось сохранить");
    }
  };

  // ---------- Курс KGS -> RUB ----------

  const rateDirty =
    settings !== null &&
    (() => {
      const n = Number(rateDraft.replace(",", "."));
      return Number.isFinite(n) && n > 0 && n !== settings.currency_kgs_to_rub_rate;
    })();

  const saveRate = async () => {
    if (!settings) return;
    const n = Number(rateDraft.replace(",", "."));
    if (!Number.isFinite(n) || n <= 0) {
      setRateError("Введите положительное число, например 0.95");
      return;
    }
    setRateSaving(true);
    setRateError(null);
    const res = await fetchData<Settings>(
      "manage/settings/",
      "PATCH",
      { currency_kgs_to_rub_rate: n },
      true
    );
    setRateSaving(false);
    if (res.ok && res.data) {
      applySnapshot(res.data);
      setRateFlash(true);
      setTimeout(() => setRateFlash(false), 2000);
    } else {
      setRateError(res.error || "Не удалось сохранить курс");
    }
  };

  // ---------- Контакты сайта ----------

  const siteDirty =
    settings !== null &&
    SITE_FIELDS.some((f) => siteDraft[f.key] !== (settings.site?.[f.key] ?? ""));

  const saveSite = async () => {
    if (!settings) return;
    const patch: Partial<SiteContacts> = {};
    for (const f of SITE_FIELDS) {
      if (siteDraft[f.key] !== (settings.site?.[f.key] ?? "")) {
        patch[f.key] = siteDraft[f.key].trim();
      }
    }
    if (Object.keys(patch).length === 0) return;
    setSiteSaving(true);
    setSiteError(null);
    const res = await fetchData<Settings>("manage/settings/", "PATCH", { site: patch }, true);
    setSiteSaving(false);
    if (res.ok && res.data) {
      applySnapshot(res.data);
      setSiteFlash(true);
      setTimeout(() => setSiteFlash(false), 2000);
    } else {
      setSiteError(res.error || "Не удалось сохранить контакты");
    }
  };

  // ---------- Рендер ----------

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-40 animate-pulse rounded-lg bg-surface-2" />
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-44 animate-pulse rounded-2xl bg-surface-2" />
        ))}
      </div>
    );
  }

  if (error || !settings) {
    return (
      <div className="rounded-2xl border border-border bg-surface p-6 text-sm text-red-400">
        Ошибка загрузки: {error || "нет данных"}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Настройки</h1>
        <p className="mt-1 text-sm text-muted">
          Ключ нейросетей, бонусы, лимиты и контакты сайта. Изменения применяются сразу после
          сохранения.
        </p>
      </div>

      {/* 1. Ключ OpenRouter */}
      <section className="rounded-2xl border border-border bg-surface p-5">
        <div className="flex items-center gap-2">
          <FiKey className="h-4 w-4 text-accent" />
          <h2 className="text-base font-semibold">Ключ OpenRouter</h2>
        </div>
        <p className="mt-1 text-xs text-muted-2">
          Ключ оплачивает ответы всех нейросетей. Меняйте только на проверенный рабочий ключ — с
          нерабочим ключом чат перестанет отвечать.
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <div className="text-sm text-muted">Текущий ключ:</div>
          <code className="rounded-lg bg-surface-2 border border-border px-3 py-1.5 font-mono text-sm">
            {settings.openrouter_key_masked || "не задан"}
          </code>
          <button
            onClick={() => runTest()}
            disabled={testing}
            className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-xs font-semibold text-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {testing ? "Проверка…" : "Проверить ключ"}
          </button>
          {keyFlash && <SavedFlash />}
        </div>

        {testResult && (
          <div
            className={`mt-3 text-sm ${testResult.ok ? "text-emerald-400" : "text-red-400"}`}
          >
            {testResult.ok
              ? `Ключ работает · баланс $${
                  testResult.balance_usd !== null ? testResult.balance_usd.toFixed(2) : "—"
                }`
              : `Ключ не работает: ${testResult.error || "неизвестная ошибка"}`}
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-end gap-3 border-t border-border pt-4">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted">Новый ключ</label>
            <div className="relative">
              <input
                type={showKey ? "text" : "password"}
                value={newKey}
                onChange={(e) => setNewKey(e.target.value)}
                placeholder="sk-or-v1-..."
                autoComplete="off"
                className={`${INPUT} w-72 pr-9 font-mono`}
              />
              <button
                type="button"
                onClick={() => setShowKey((v) => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-foreground"
                aria-label={showKey ? "Скрыть ключ" : "Показать ключ"}
              >
                {showKey ? <FiEyeOff className="h-4 w-4" /> : <FiEye className="h-4 w-4" />}
              </button>
            </div>
          </div>
          <button
            onClick={replaceKey}
            disabled={keySaving || !newKey.trim()}
            className="rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {keySaving ? "Замена…" : "Заменить ключ"}
          </button>
        </div>
        {keyError && <div className="mt-2 text-sm text-red-400">{keyError}</div>}
      </section>

      {/* 2. Бонусы и лимиты */}
      <section className="rounded-2xl border border-border bg-surface p-5">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <FiGift className="h-4 w-4 text-accent" />
            <h2 className="text-base font-semibold">Бонусы и лимиты</h2>
          </div>
          <div className="flex items-center gap-3">
            {bonusFlash && <SavedFlash />}
            {bonusDirty && (
              <button
                onClick={saveBonuses}
                disabled={bonusSaving}
                className="rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {bonusSaving ? "Сохранение…" : "Сохранить"}
              </button>
            )}
          </div>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {NUM_FIELDS.map((f) => (
            <div key={f.key} className="flex flex-col gap-1">
              <label className="text-xs text-muted">{f.label}</label>
              <input
                type="number"
                min={0}
                max={f.max}
                step={1}
                value={numDraft[f.key]}
                onChange={(e) =>
                  setNumDraft((d) => ({ ...d, [f.key]: e.target.value }))
                }
                className={INPUT}
              />
              <span className="text-xs text-muted-2">{f.sub}</span>
            </div>
          ))}
        </div>

        {/* 3. Генерация изображений (сохраняется той же кнопкой «Сохранить») */}
        <div className="mt-5 border-t border-border pt-4">
          <div className="flex items-center gap-2">
            <FiImage className="h-4 w-4 text-accent" />
            <h3 className="text-sm font-semibold">Генерация изображений</h3>
          </div>
          <label className="mt-3 inline-flex cursor-pointer items-start gap-3">
            <input
              type="checkbox"
              checked={imageAutoRoute}
              onChange={(e) => setImageAutoRoute(e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-accent"
            />
            <span className="text-sm">
              Авто-рисование
              <span className="block text-xs text-muted-2">
                Запрос «нарисуй…» уходит модели изображений автоматически. Сохраняется кнопкой
                «Сохранить» этой секции.
              </span>
            </span>
          </label>
        </div>

        {bonusError && <div className="mt-3 text-sm text-red-400">{bonusError}</div>}
      </section>

      {/* 3.5 Курс валют: KGS -> RUB (переключатель на /pricing, задача ЮKassa) */}
      <section className="rounded-2xl border border-border bg-surface p-5">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <FiDollarSign className="h-4 w-4 text-accent" />
            <h2 className="text-base font-semibold">Курс валют (KGS → RUB)</h2>
          </div>
          <div className="flex items-center gap-3">
            {rateFlash && <SavedFlash />}
            {rateDirty && (
              <button
                onClick={saveRate}
                disabled={rateSaving}
                className="rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {rateSaving ? "Сохранение…" : "Сохранить"}
              </button>
            )}
          </div>
        </div>
        <p className="mt-1 text-xs text-muted-2">
          Витринный курс для переключателя валют на /pricing (клиент показывает цены и в рублях
          для ЮKassa). Реальная оплата всегда идёт через FreedomPay в сомах — этот курс ТОЛЬКО
          пересчитывает отображаемую цену. Проверяйте и обновляйте под актуальный рыночный курс.
        </p>
        <div className="mt-4 flex flex-col gap-1 max-w-xs">
          <label className="text-xs text-muted">1 сом = ? рублей</label>
          <input
            type="text"
            inputMode="decimal"
            value={rateDraft}
            onChange={(e) => setRateDraft(e.target.value)}
            placeholder="0.95"
            className={INPUT}
          />
        </div>
        {rateError && <div className="mt-3 text-sm text-red-400">{rateError}</div>}
      </section>

      {/* 4. Контакты сайта */}
      <section className="rounded-2xl border border-border bg-surface p-5">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <FiPhone className="h-4 w-4 text-accent" />
            <h2 className="text-base font-semibold">Контакты сайта</h2>
          </div>
          <div className="flex items-center gap-3">
            {siteFlash && <SavedFlash />}
            {siteDirty && (
              <button
                onClick={saveSite}
                disabled={siteSaving}
                className="rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {siteSaving ? "Сохранение…" : "Сохранить"}
              </button>
            )}
          </div>
        </div>
        <p className="mt-1 text-xs text-muted-2">Показываются в подвале сайта.</p>

        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {SITE_FIELDS.map((f) => (
            <div key={f.key} className="flex flex-col gap-1">
              <label className="text-xs text-muted">{f.label}</label>
              <input
                type="text"
                value={siteDraft[f.key]}
                onChange={(e) =>
                  setSiteDraft((d) => ({ ...d, [f.key]: e.target.value }))
                }
                placeholder={f.placeholder}
                className={INPUT}
              />
            </div>
          ))}
        </div>

        {siteError && <div className="mt-3 text-sm text-red-400">{siteError}</div>}
      </section>
    </div>
  );
}
