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
  FiMic,
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
  referral_percent: number;
  daily_retention_target: number;
  web_search_surcharge: number;
  free_daily_requests: number;
  paid_daily_requests: number;
  image_auto_route: boolean;
  currency_kgs_to_rub_rate: number;
  // --- криптооплата ---
  crypto_payments_mode: "off" | "staff" | "on";
  crypto_configured: boolean;
  nowpayments_key_masked: string | null;
  nowpayments_ipn_secret_masked: string | null;
  nowpayments_sandbox: boolean;
  crypto_fee_paid_by_user: boolean;
  nowpayments_fixed_rate: boolean;
  crypto_allowed_currencies: string;
  crypto_settlement_currency: string;
  elevenlabs_configured?: boolean;
  elevenlabs_key_masked?: string | null;
  studio_voice_credits_per_1k?: number;
  studio_voice_min_credits?: number;
  studio_music_credits_per_min?: number;
  studio_sfx_credits?: number;
  /** курс, по которому реально выставляется криптосчёт */
  currency_kgs_to_usd_rate: number;
  /** зафиксированный админом вручную (0 — не задан, берётся живой) */
  currency_kgs_to_usd_manual: number;
  /** живой рыночный курс — для сравнения */
  currency_kgs_to_usd_market: number | null;
  site: SiteContacts;
};

type CryptoTestResult = {
  ok: boolean;
  error?: string | null;
  sandbox?: boolean;
  coins?: number;
  ipn_secret_set?: boolean;
};

/** Монеты, которые можно включить. Коды — как их называет процессор. */
const CRYPTO_COINS: { code: string; label: string }[] = [
  { code: "usdttrc20", label: "USDT · TRON (TRC-20)" },
  { code: "usdtton", label: "USDT · TON" },
  { code: "usdtbsc", label: "USDT · BNB Smart Chain" },
  { code: "usdterc20", label: "USDT · Ethereum (дорогая сеть)" },
  { code: "btc", label: "Bitcoin" },
  { code: "eth", label: "Ethereum" },
  { code: "ton", label: "GRAM (Toncoin)" },
  { code: "ltc", label: "Litecoin" },
  { code: "trx", label: "TRON" },
  { code: "bnbbsc", label: "BNB" },
  { code: "sol", label: "Solana" },
  { code: "doge", label: "Dogecoin" },
];

const CRYPTO_MODES: { value: "off" | "staff" | "on"; label: string; hint: string }[] = [
  { value: "off", label: "Выключено", hint: "способа оплаты нет ни у кого" },
  { value: "staff", label: "Только сотрудникам", hint: "для проверки боевых ключей" },
  { value: "on", label: "Включено", hint: "видно всем" },
];

type TestResult = {
  ok: boolean;
  balance_usd: number | null;
  error: string | null;
};

const INPUT =
  "rounded-lg bg-surface-2 border border-border px-3 py-2 text-sm text-foreground focus:border-accent outline-none";

type NumKey =
  | "welcome_bonus"
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
  // «Реферальный бонус (кр)» убран: REFERRAL_BONUS_TOKENS нигде в логике не
  // используется (программа платит только % с пополнений), поле ничего не меняло.
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

type AudioPriceKey =
  | "studio_voice_credits_per_1k"
  | "studio_voice_min_credits"
  | "studio_music_credits_per_min"
  | "studio_sfx_credits";

const AUDIO_PRICES: { key: AudioPriceKey; label: string }[] = [
  { key: "studio_voice_credits_per_1k", label: "Озвучка: кредитов за 1000 символов" },
  { key: "studio_voice_min_credits", label: "Озвучка: минимум за генерацию" },
  { key: "studio_music_credits_per_min", label: "Музыка: кредитов за минуту" },
  { key: "studio_sfx_credits", label: "Звуковой эффект: кредитов" },
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

  // --- Секция: криптооплата ---
  const [cryptoMode, setCryptoMode] = useState<"off" | "staff" | "on">("off");
  const [cryptoCoins, setCryptoCoins] = useState<string[]>([]);
  const [feeByUser, setFeeByUser] = useState(false);
  const [usdRateDraft, setUsdRateDraft] = useState("");
  const [settleDraft, setSettleDraft] = useState("");
  const [npKey, setNpKey] = useState("");
  const [npSecret, setNpSecret] = useState("");
  const [cryptoSaving, setCryptoSaving] = useState(false);
  const [cryptoError, setCryptoError] = useState<string | null>(null);
  const [cryptoFlash, setCryptoFlash] = useState(false);
  const [cryptoTesting, setCryptoTesting] = useState(false);
  const [cryptoTest, setCryptoTest] = useState<CryptoTestResult | null>(null);

  // --- Звук студии (ElevenLabs) ---
  const [elKey, setElKey] = useState("");
  const [audioDraft, setAudioDraft] = useState<Record<AudioPriceKey, string>>({
    studio_voice_credits_per_1k: "",
    studio_voice_min_credits: "",
    studio_music_credits_per_min: "",
    studio_sfx_credits: "",
  });
  const [audioSaving, setAudioSaving] = useState(false);
  const [audioError, setAudioError] = useState<string | null>(null);
  const [audioFlash, setAudioFlash] = useState(false);
  const [audioTesting, setAudioTesting] = useState(false);
  const [audioTest, setAudioTest] = useState<{ ok: boolean; error?: string | null; voices?: number } | null>(null);

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

  // Черновики каждой секции синхронизируются со снимком ОТДЕЛЬНО. Раньше
  // после сохранения любой секции перезаписывались все поля страницы —
  // несохранённые правки в соседних секциях молча пропадали.
  const syncBonusDraft = (s: Settings) => {
    setNumDraft({
      welcome_bonus: String(s.welcome_bonus ?? 0),
      referral_percent: String(s.referral_percent ?? 0),
      daily_retention_target: String(s.daily_retention_target ?? 0),
      web_search_surcharge: String(s.web_search_surcharge ?? 0),
      free_daily_requests: String(s.free_daily_requests ?? 0),
      paid_daily_requests: String(s.paid_daily_requests ?? 0),
    });
    setImageAutoRoute(Boolean(s.image_auto_route));
  };

  const syncAudioDraft = (s: Settings) => {
    setAudioDraft({
      studio_voice_credits_per_1k: String(s.studio_voice_credits_per_1k ?? 20),
      studio_voice_min_credits: String(s.studio_voice_min_credits ?? 5),
      studio_music_credits_per_min: String(s.studio_music_credits_per_min ?? 30),
      studio_sfx_credits: String(s.studio_sfx_credits ?? 10),
    });
  };

  const syncRateDraft = (s: Settings) => {
    setRateDraft(String(s.currency_kgs_to_rub_rate ?? ""));
  };

  const syncCryptoDraft = (s: Settings) => {
    setCryptoMode(s.crypto_payments_mode ?? "off");
    setFeeByUser(Boolean(s.crypto_fee_paid_by_user));
    setCryptoCoins(
      String(s.crypto_allowed_currencies || "")
        .split(",")
        .map((c) => c.trim())
        .filter(Boolean)
    );
    // Пустое поле означает «брать живой курс» — так и показываем.
    setUsdRateDraft(s.currency_kgs_to_usd_manual ? String(s.currency_kgs_to_usd_manual) : "");
    setSettleDraft(String(s.crypto_settlement_currency || ""));
  };

  const syncSiteDraft = (s: Settings) => {
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

  /** Первая загрузка: заполняем все секции. */
  const applySnapshot = (s: Settings) => {
    setSettings(s);
    syncBonusDraft(s);
    syncAudioDraft(s);
    syncRateDraft(s);
    syncCryptoDraft(s);
    syncSiteDraft(s);
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
      setSettings(res.data);
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
      setSettings(res.data);
      syncBonusDraft(res.data);
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
      setSettings(res.data);
      syncRateDraft(res.data);
      setRateFlash(true);
      setTimeout(() => setRateFlash(false), 2000);
    } else {
      setRateError(res.error || "Не удалось сохранить курс");
    }
  };

  // ---------- Криптооплата ----------

  const cryptoDirty =
    settings !== null &&
    (cryptoMode !== settings.crypto_payments_mode ||
      feeByUser !== Boolean(settings.crypto_fee_paid_by_user) ||
      cryptoCoins.join(",") !== settings.crypto_allowed_currencies ||
      Boolean(npKey.trim()) ||
      Boolean(npSecret.trim()) ||
      settleDraft.trim().toLowerCase() !== String(settings.crypto_settlement_currency || "") ||
      usdRateDraft.trim() !==
        (settings.currency_kgs_to_usd_manual ? String(settings.currency_kgs_to_usd_manual) : ""));

  const saveCrypto = async () => {
    if (!settings) return;
    const patch: Record<string, unknown> = {};
    if (cryptoMode !== settings.crypto_payments_mode) {
      if (cryptoMode !== "off" && !(settings.crypto_configured || npKey.trim())) {
        setCryptoError("Сначала введите API-ключ NOWPayments.");
        return;
      }
      patch.crypto_payments_mode = cryptoMode;
    }
    if (cryptoCoins.join(",") !== settings.crypto_allowed_currencies) {
      patch.crypto_allowed_currencies = cryptoCoins.join(",");
    }
    if (feeByUser !== Boolean(settings.crypto_fee_paid_by_user)) {
      patch.crypto_fee_paid_by_user = feeByUser;
    }
    if (npKey.trim()) patch.nowpayments_api_key = npKey.trim();
    if (npSecret.trim()) patch.nowpayments_ipn_secret = npSecret.trim();
    if (settleDraft.trim().toLowerCase() !== String(settings.crypto_settlement_currency || "")) {
      patch.crypto_settlement_currency = settleDraft.trim().toLowerCase();
    }

    const manual = usdRateDraft.trim().replace(",", ".");
    const currentManual = settings.currency_kgs_to_usd_manual
      ? String(settings.currency_kgs_to_usd_manual)
      : "";
    if (manual !== currentManual) {
      if (manual === "") {
        patch.currency_kgs_to_usd_rate = "";
      } else {
        const n = Number(manual);
        if (!Number.isFinite(n) || n <= 0 || n > 1) {
          setCryptoError("Курс сом → доллар: число от 0 до 1, например 0.0114");
          return;
        }
        patch.currency_kgs_to_usd_rate = n;
      }
    }
    if (Object.keys(patch).length === 0) return;

    setCryptoSaving(true);
    setCryptoError(null);
    const res = await fetchData<Settings>("manage/settings/", "PATCH", patch, true);
    setCryptoSaving(false);
    if (res.ok && res.data) {
      setSettings(res.data);
      syncCryptoDraft(res.data);
      setNpKey("");
      setNpSecret("");
      setCryptoFlash(true);
      setTimeout(() => setCryptoFlash(false), 2000);
    } else {
      setCryptoError(res.error || "Не удалось сохранить");
    }
  };

  const testCrypto = async () => {
    setCryptoTesting(true);
    setCryptoTest(null);
    const res = await fetchData<CryptoTestResult>(
      "manage/settings/test-nowpayments/",
      "POST",
      {},
      true
    );
    setCryptoTesting(false);
    setCryptoTest(
      res.ok && res.data ? res.data : { ok: false, error: res.error || "Нет связи" }
    );
  };

  // ---------- Звук студии ----------

  const audioDirty =
    settings !== null &&
    (Boolean(elKey.trim()) ||
      AUDIO_PRICES.some((f) => audioDraft[f.key] !== String(settings[f.key] ?? "")));

  const saveAudio = async () => {
    if (!settings) return;
    const patch: Record<string, unknown> = {};
    for (const f of AUDIO_PRICES) {
      if (audioDraft[f.key] === String(settings[f.key] ?? "")) continue;
      const n = Number(audioDraft[f.key]);
      if (!Number.isInteger(n) || n < 0) {
        setAudioError(`${f.label}: целое число от 0`);
        return;
      }
      patch[f.key] = n;
    }
    if (elKey.trim()) patch.elevenlabs_api_key = elKey.trim();
    if (Object.keys(patch).length === 0) return;
    setAudioSaving(true);
    setAudioError(null);
    const res = await fetchData<Settings>("manage/settings/", "PATCH", patch, true);
    setAudioSaving(false);
    if (res.ok && res.data) {
      setSettings(res.data);
      syncAudioDraft(res.data);
      setElKey("");
      setAudioFlash(true);
      setTimeout(() => setAudioFlash(false), 2000);
    } else {
      setAudioError(res.error || "Не удалось сохранить");
    }
  };

  const testAudio = async () => {
    setAudioTesting(true);
    setAudioTest(null);
    const res = await fetchData<{ ok: boolean; error?: string | null; voices?: number }>(
      "manage/settings/test-elevenlabs/",
      "POST",
      {},
      true
    );
    setAudioTesting(false);
    setAudioTest(res.ok && res.data ? res.data : { ok: false, error: res.error || "Нет связи" });
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
      setSettings(res.data);
      syncSiteDraft(res.data);
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

      {/* 3.6 Криптооплата (NOWPayments) */}
      <section className="rounded-2xl border border-border bg-surface p-5">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <FiDollarSign className="h-4 w-4 text-accent" />
            <h2 className="text-base font-semibold">Криптооплата (NOWPayments)</h2>
          </div>
          <div className="flex items-center gap-3">
            {cryptoFlash && <SavedFlash />}
            <button
              onClick={testCrypto}
              disabled={cryptoTesting}
              className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-xs font-semibold text-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {cryptoTesting ? "Проверка…" : "Проверить подключение"}
            </button>
            {cryptoDirty && (
              <button
                onClick={saveCrypto}
                disabled={cryptoSaving}
                className="rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {cryptoSaving ? "Сохранение…" : "Сохранить"}
              </button>
            )}
          </div>
        </div>
        <p className="mt-1 text-xs text-muted-2">
          Адрес и сумму выдаёт процессор, он же следит за сетью. Кредиты начисляются только
          после подтверждения перевода. {settings.nowpayments_sandbox
            ? "Сейчас включена ПЕСОЧНИЦА (NOWPAYMENTS_SANDBOX=1): настоящие деньги не принимаются."
            : "Режим боевой."}
        </p>

        {cryptoTest && (
          <div className={`mt-3 text-sm ${cryptoTest.ok ? "text-emerald-400" : "text-red-400"}`}>
            {cryptoTest.ok
              ? `Подключение работает · монет включено у процессора: ${cryptoTest.coins ?? "—"}` +
                (cryptoTest.ipn_secret_set ? "" : " · ВНИМАНИЕ: не задан IPN-секрет")
              : `Не работает: ${cryptoTest.error || "неизвестная ошибка"}`}
          </div>
        )}

        <div className="mt-4 flex flex-wrap gap-2">
          {CRYPTO_MODES.map((m) => (
            <button
              key={m.value}
              onClick={() => setCryptoMode(m.value)}
              title={m.hint}
              className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                cryptoMode === m.value
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border text-muted hover:text-foreground"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>

        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted">
              API-ключ (текущий: {settings.nowpayments_key_masked || "не задан"})
            </label>
            <input
              type="password"
              value={npKey}
              onChange={(e) => setNpKey(e.target.value)}
              placeholder="новый ключ"
              autoComplete="off"
              className={`${INPUT} font-mono`}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted">
              IPN-секрет (текущий: {settings.nowpayments_ipn_secret_masked || "не задан"})
            </label>
            <input
              type="password"
              value={npSecret}
              onChange={(e) => setNpSecret(e.target.value)}
              placeholder="новый секрет"
              autoComplete="off"
              className={`${INPUT} font-mono`}
            />
          </div>
        </div>

        <label className="mt-4 flex max-w-xl cursor-pointer items-start gap-3 rounded-xl border border-border bg-surface-2 px-3 py-2.5">
          <input
            type="checkbox"
            checked={feeByUser}
            onChange={(e) => setFeeByUser(e.target.checked)}
            className="mt-0.5 h-4 w-4 accent-[var(--accent)]"
          />
          <span className="flex flex-col gap-0.5">
            <span className="text-sm text-foreground">Комиссию процессора платит покупатель</span>
            <span className="text-[11px] text-muted-2">
              Включено: комиссия NOWPayments (0.5%) и сети добавляется к сумме перевода, и вы
              получаете полную цену пакета. Выключено: комиссия вычитается из выручки.
            </span>
            <span className="text-[11px] text-status-wait">
              Осторожно: с включённым флагом процессор поднимает минимальную сумму счёта
              примерно до $6–11 — пакеты дешевле перестают оплачиваться криптой (проверено
              6 сентября: $2.17 и $5.60 отвергались, без флага $2.17 принимался).
            </span>
            <span className="text-[11px] text-muted-2">
              {settings.nowpayments_fixed_rate
                ? " Курс на время счёта фиксируется (NOWPAYMENTS_FIXED_RATE=1) — минимальные суммы выше."
                : " Курс плавающий: так минимальная сумма у процессора почти вдвое ниже."}
            </span>
          </span>
        </label>

        <div className="mt-4 flex flex-col gap-1 max-w-sm">
          <label className="text-xs text-muted">
            Курс: 1 сом = ? долларов (пусто — брать живой курс)
          </label>
          <input
            type="text"
            inputMode="decimal"
            value={usdRateDraft}
            onChange={(e) => setUsdRateDraft(e.target.value)}
            placeholder={String(settings.currency_kgs_to_usd_market ?? 0.0115)}
            className={INPUT}
          />
          <span className="text-[11px] text-muted-2">
            Сейчас счёт выставляется по {settings.currency_kgs_to_usd_rate}
            {settings.currency_kgs_to_usd_market
              ? ` · рыночный ${settings.currency_kgs_to_usd_market}`
              : " · живой курс недоступен"}
            . В отличие от рублёвого, этот курс ПЛАТЁЖНЫЙ: по нему человек переводит деньги.
          </span>
        </div>

        <div className="mt-4 flex flex-col gap-1 max-w-sm">
          <label className="text-xs text-muted">
            Валюта кошелька выплат в NOWPayments (код процессора, например usdtbsc)
          </label>
          <input
            type="text"
            value={settleDraft}
            onChange={(e) => setSettleDraft(e.target.value)}
            placeholder="usdtbsc"
            autoComplete="off"
            className={`${INPUT} font-mono`}
          />
          <span className="text-[11px] text-muted-2">
            По этой паре процессор считает минимальную сумму счёта. Без неё справочник
            показывает минимумы «в доллар» — до $12 для монет, которыми на самом деле
            принимаются $2, и витрина зря их гасит. Поменяли кошелёк выплат в кабинете —
            поменяйте и здесь.
          </span>
        </div>

        <div className="mt-4">
          <div className="text-xs text-muted">Монеты на витрине</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {CRYPTO_COINS.map((c) => {
              const on = cryptoCoins.includes(c.code);
              return (
                <button
                  key={c.code}
                  onClick={() =>
                    setCryptoCoins((prev) =>
                      prev.includes(c.code)
                        ? prev.filter((x) => x !== c.code)
                        : [...prev, c.code]
                    )
                  }
                  className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                    on
                      ? "border-accent bg-accent/10 text-accent"
                      : "border-border text-muted hover:text-foreground"
                  }`}
                >
                  {c.label}
                </button>
              );
            })}
          </div>
        </div>

        {cryptoError && <div className="mt-3 text-sm text-red-400">{cryptoError}</div>}
      </section>

      {/* Звук студии */}
      <section className="rounded-2xl border border-border bg-surface p-5">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <FiMic className="h-4 w-4 text-accent" />
            <h2 className="text-base font-semibold">Озвучка студии (ElevenLabs)</h2>
          </div>
          <div className="flex items-center gap-3">
            {audioFlash && <SavedFlash />}
            <button
              onClick={testAudio}
              disabled={audioTesting}
              className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-xs font-semibold text-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {audioTesting ? "Проверка…" : "Проверить ключ"}
            </button>
            {audioDirty && (
              <button
                onClick={saveAudio}
                disabled={audioSaving}
                className="rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {audioSaving ? "Сохранение…" : "Сохранить"}
              </button>
            )}
          </div>
        </div>
        <p className="mt-1 text-xs text-muted-2">
          Голоса, музыка и звуковые эффекты в сценах. Пока ключ не задан, кнопка «Звук» в студии
          не показывается. Кредиты списываются только за готовый звук, цену человек видит до
          генерации. {settings.elevenlabs_configured ? "Ключ задан." : "Ключ НЕ задан."}
        </p>

        {audioTest && (
          <div className={`mt-3 text-sm ${audioTest.ok ? "text-emerald-400" : "text-red-400"}`}>
            {audioTest.ok
              ? `Ключ работает · готовых голосов: ${audioTest.voices ?? "—"}`
              : `Не работает: ${audioTest.error || "неизвестная ошибка"}`}
          </div>
        )}

        <div className="mt-4 flex max-w-xl flex-col gap-1">
          <label className="text-xs text-muted">
            API-ключ (текущий: {settings.elevenlabs_key_masked || "не задан"})
          </label>
          <input
            type="password"
            value={elKey}
            onChange={(e) => setElKey(e.target.value)}
            placeholder="новый ключ sk_…"
            autoComplete="off"
            className={`${INPUT} font-mono`}
          />
          <span className="text-[11px] text-muted-2">
            Ключу нужны права: Text to Speech, Sound Effects, Music, Voices (read).
          </span>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {AUDIO_PRICES.map((f) => (
            <div key={f.key} className="flex flex-col gap-1">
              <label className="text-xs text-muted">{f.label}</label>
              <input
                type="text"
                inputMode="numeric"
                value={audioDraft[f.key]}
                onChange={(e) => setAudioDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                className={INPUT}
              />
            </div>
          ))}
        </div>

        {audioError && <div className="mt-3 text-sm text-red-400">{audioError}</div>}
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
