"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchData } from "@/tools/fetchData";
import {
  FiKey,
  FiGift,
  FiImage,
  FiPhone,
  FiEye,
  FiEyeOff,
  FiCheck,
  FiCreditCard,
  FiDollarSign,
  FiMic,
  FiFilm,
  FiGrid,
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

type GoPayMode = "off" | "staff" | "on";
type GoPayEnv = "test" | "live";
type GoPaySecretField = "api_key" | "api_secret" | "webhook_secret";

/** Что известно о ключах среды. Самих значений сервер не отдаёт никогда. */
type GoPayKeyState = {
  api_key_set: boolean;
  /** «…a1b2» — хвост публичного ключа; у секретов нет и его */
  api_key_tail: string;
  api_secret_set: boolean;
  webhook_secret_set: boolean;
};

type GoPayHealth = {
  ok: boolean;
  fails: number;
  kind: string;
  code: string;
  since: string | null;
  down: boolean;
};

/** Блок «Единый QR (GoPay)» в снимке настроек. */
type GoPaySettings = {
  mode: GoPayMode;
  env: GoPayEnv;
  lifetime_minutes: number;
  send_buyer_email: boolean;
  /** у активной среды есть ключ и секрет */
  configured: boolean;
  /** кому сервер готов показать QR: всем / сотрудникам */
  effective: { public: boolean; staff: boolean };
  webhook_url: string;
  webhook_events: string[];
  webhook_events_optional?: string[];
  api_host: string;
  test: GoPayKeyState;
  live: GoPayKeyState;
  // Три ключа ниже считает отдельный вызов сервера: при сбое их просто нет.
  health?: Partial<Record<GoPayEnv, GoPayHealth>>;
  in_flight?: Partial<Record<GoPayEnv, number>>;
  unsettled?: number;
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
  studio_scene_credits?: number;
  /** курс, по которому реально выставляется криптосчёт */
  currency_kgs_to_usd_rate: number;
  /** зафиксированный админом вручную (0 — не задан, берётся живой) */
  currency_kgs_to_usd_manual: number;
  /** живой рыночный курс — для сравнения */
  currency_kgs_to_usd_market: number | null;
  // --- видеостудия ---
  /** действующий режим (правка админки поверх окружения) */
  vstudio_mode?: "off" | "staff" | "on";
  /** VSTUDIO_MODE из окружения */
  vstudio_mode_env?: string;
  /** правка из админки; "" — не задана, действует окружение */
  vstudio_mode_override?: string;
  // --- оплата в сомах: выбор способа до ухода на Freedom Pay ---
  kgs_methods_mode?: "off" | "staff" | "on";
  /** включённые способы Freedom Pay через запятую (единого QR здесь нет: он идёт через GoPay) */
  kgs_methods_enabled?: string;
  /** код единого QR от Freedom Pay; хранится на будущее, кнопку не включает */
  kgs_elqr_ps_code?: string;
  /** все способы, которые знает сервер, в порядке показа */
  kgs_methods_known?: string[];
  /** единый QR через GoPay; у старого сервера ключа нет — блок тогда не показываем */
  gopay?: GoPaySettings;
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
  | "studio_sfx_credits"
  | "studio_scene_credits";

const AUDIO_PRICES: { key: AudioPriceKey; label: string }[] = [
  { key: "studio_voice_credits_per_1k", label: "Озвучка: кредитов за 1000 символов" },
  { key: "studio_voice_min_credits", label: "Озвучка: минимум за генерацию" },
  { key: "studio_music_credits_per_min", label: "Музыка: кредитов за минуту" },
  { key: "studio_sfx_credits", label: "Звуковой эффект: кредитов" },
  // Цена сцены (5 с) целиком — кадр + видео; 0 — по тарифу видеомодели
  // (он же цена видео в чате, поэтому у мультфильмов своя цена).
  { key: "studio_scene_credits", label: "Мультфильм: цена сцены 5 с (0 — по тарифу модели)" },
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
    studio_scene_credits: "",
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
      studio_scene_credits: String(s.studio_scene_credits ?? 0),
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

      {/* 3.65 Единый QR (GoPay) */}
      <GoPaySection settings={settings} onSaved={setSettings} />

      {/* 3.7 Оплата в сомах: выбор способа */}
      <KgsMethodsSection settings={settings} onSaved={setSettings} />

      {/* 3.8 Видеостудия: режим */}
      <VStudioModeSection settings={settings} onSaved={setSettings} />

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

type VsModeValue = "" | "off" | "staff" | "on";

const VSTUDIO_MODES: { value: VsModeValue; label: string; hint: string }[] = [
  { value: "", label: "Как в окружении", hint: "Убрать правку из админки — действует VSTUDIO_MODE сервера" },
  { value: "off", label: "Выключена", hint: "Студия закрыта для всех: «Видеостудия скоро откроется»" },
  { value: "staff", label: "Только сотрудники", hint: "Генерировать могут только is_staff, остальные видят «скоро откроется»" },
  { value: "on", label: "Для всех", hint: "Студия открыта всем; гости видят цены и входят, чтобы запустить" },
];

/**
 * Видеостудия (/video-studio): режим off/staff/on без выкладки. Пункт меню и
 * sitemap включаются отдельно — сборкой с NEXT_PUBLIC_VSTUDIO_NAV=1.
 */
function VStudioModeSection({ settings, onSaved }: { settings: Settings; onSaved: (s: Settings) => void }) {
  const current = (settings.vstudio_mode_override || "") as VsModeValue;
  const [draft, setDraft] = useState<VsModeValue>(current);
  const [saving, setSaving] = useState(false);
  const [flash, setFlash] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Сохранили (или перечитали настройки) — черновик снова равен сохранённому.
  const [prevCurrent, setPrevCurrent] = useState<VsModeValue>(current);
  if (current !== prevCurrent) {
    setPrevCurrent(current);
    setDraft(current);
  }

  const save = async () => {
    setSaving(true);
    setErr(null);
    const res = await fetchData<Settings>("manage/settings/", "PATCH", { vstudio_mode: draft }, true);
    setSaving(false);
    if (res.ok && res.data) {
      onSaved(res.data);
      setFlash(true);
      setTimeout(() => setFlash(false), 2000);
    } else {
      setErr(res.error || "Не удалось сохранить");
    }
  };

  const label = (m?: string) => VSTUDIO_MODES.find((x) => x.value === m)?.label || m || "—";

  return (
    <section className="rounded-2xl border border-border bg-surface p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <FiFilm className="h-4 w-4 text-accent" />
          <h2 className="text-base font-semibold">Видеостудия</h2>
        </div>
        <div className="flex items-center gap-3">
          {flash && <SavedFlash />}
          {draft !== current && (
            <button
              onClick={save}
              disabled={saving}
              className="rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {saving ? "Сохранение…" : "Сохранить"}
            </button>
          )}
        </div>
      </div>
      <p className="mt-1 text-xs text-muted-2">
        Сейчас: <span className="text-foreground">{label(settings.vstudio_mode)}</span> · в окружении:{" "}
        {label(settings.vstudio_mode_env)}. Пункт «Видеостудия» в меню сайта появляется только в сборке с
        NEXT_PUBLIC_VSTUDIO_NAV=1.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        {VSTUDIO_MODES.map((m) => (
          <button
            key={m.value || "env"}
            onClick={() => setDraft(m.value)}
            title={m.hint}
            className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
              draft === m.value ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:text-foreground"
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>
      {err && <div className="mt-3 text-sm text-red-400">{err}</div>}
    </section>
  );
}

const GOPAY_MODES: { value: GoPayMode; label: string; hint: string }[] = [
  {
    value: "off",
    label: "Выключено",
    hint: "кнопки «Единый QR» нет ни у кого; уже выставленные счета досверяются и зачисляются, если их оплатят",
  },
  { value: "staff", label: "Только сотрудникам", hint: "QR видят только сотрудники — для проверки перед запуском" },
  {
    value: "on",
    label: "Включено",
    hint: "QR видят все покупатели; в тестовой среде — всё равно только сотрудники",
  },
];

const GOPAY_ENVS: { value: GoPayEnv; label: string; hint: string }[] = [
  {
    value: "test",
    label: "Тест",
    hint: "работает тестовая пара ключей: оплата имитируется, деньги не списываются, QR видят только сотрудники",
  },
  { value: "live", label: "Боевая", hint: "работает боевая пара ключей: платежи настоящие" },
];

const GOPAY_ENV_KEYS: GoPayEnv[] = ["test", "live"];

const GOPAY_SECRET_FIELDS: { key: GoPaySecretField; label: string }[] = [
  { key: "api_key", label: "API-ключ" },
  { key: "api_secret", label: "API-секрет" },
  { key: "webhook_secret", label: "Секрет вебхуков" },
];

// То же правило, что на сервере: печатные латинские символы без пробелов, 8–256.
const GOPAY_SECRET_RE = /^[\x21-\x7E]{8,256}$/;
const GOPAY_LIFETIME_MIN = 5;
const GOPAY_LIFETIME_MAX = 1440;

const GOPAY_NO_KEYS: GoPayKeyState = {
  api_key_set: false,
  api_key_tail: "",
  api_secret_set: false,
  webhook_secret_set: false,
};

/** Причина сбоя словами: сервер отдаёт короткий код вида сбоя. */
const GOPAY_HEALTH_KIND: Record<string, string> = {
  unavailable: "нет ответа",
  auth: "ключ или подпись не приняты",
  org_inactive: "код 0016",
  not_configured: "ключи не заданы",
};

type GoPaySecretDraft = Record<GoPaySecretField, string>;

const goPayEmptySecrets = (): Record<GoPayEnv, GoPaySecretDraft> => ({
  test: { api_key: "", api_secret: "", webhook_secret: "" },
  live: { api_key: "", api_secret: "", webhook_secret: "" },
});

type GoPayTestResult = {
  ok: boolean;
  env?: string;
  /** сколько приложений банков вернул GoPay; у тестового ключа бывает 0 */
  apps?: number | null;
  webhook_secret_set?: boolean;
  error?: string | null;
  provider_code?: string | null;
};

const goPayEnvName = (env: GoPayEnv, form: "nom" | "gen" = "nom"): string =>
  env === "test" ? (form === "gen" ? "тестовой" : "тестовая") : form === "gen" ? "боевой" : "боевая";

const goPaySince = (iso: string | null | undefined): string => {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};

async function goPayCopy(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Буфер недоступен (http, старый webview) — пробуем через textarea.
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}

/**
 * Единый QR через GoPay. Старый сервер ключа `gopay` не присылает — тогда
 * блока нет вовсе, а не пустая форма, которая ничего не сохраняет.
 */
function GoPaySection({ settings, onSaved }: { settings: Settings; onSaved: (s: Settings) => void }) {
  if (!settings.gopay) return null;
  return <GoPayPanel gopay={settings.gopay} kgsMode={settings.kgs_methods_mode ?? "off"} onSaved={onSaved} />;
}

/**
 * Режим, среда, срок жизни QR и ключи GoPay. Ключи — только на запись: сервер
 * отдаёт «задан / не задан» и хвост публичного ключа, поэтому поля всегда
 * пустые, а пустое поле при сохранении значит «не трогать».
 */
function GoPayPanel({
  gopay,
  kgsMode,
  onSaved,
}: {
  gopay: GoPaySettings;
  kgsMode: KgsMode;
  onSaved: (s: Settings) => void;
}) {
  const savedMode: GoPayMode = gopay.mode ?? "off";
  const savedEnv: GoPayEnv = gopay.env === "live" ? "live" : "test";
  const savedLifetime = String(gopay.lifetime_minutes ?? 15);
  const savedEmail = Boolean(gopay.send_buyer_email);

  const [mode, setMode] = useState<GoPayMode>(savedMode);
  const [env, setEnv] = useState<GoPayEnv>(savedEnv);
  const [lifetime, setLifetime] = useState(savedLifetime);
  const [sendEmail, setSendEmail] = useState(savedEmail);
  const [secrets, setSecrets] = useState(goPayEmptySecrets);
  const [saving, setSaving] = useState(false);
  /** какое поле сейчас удаляется: «test.api_key» */
  const [removing, setRemoving] = useState<string | null>(null);
  const [flash, setFlash] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [testing, setTesting] = useState<GoPayEnv | null>(null);
  const [tests, setTests] = useState<Partial<Record<GoPayEnv, GoPayTestResult>>>({});
  const [copied, setCopied] = useState<"ok" | "fail" | null>(null);
  // Сервер отказал в удалении из-за незавершённых счетов (409): запоминаем их
  // число, чтобы повторное «Удалить» спросило уже про них и ушло с force.
  const [inFlightSeen, setInFlightSeen] = useState<Partial<Record<GoPayEnv, number>>>({});

  // Сохранили (или перечитали настройки) — черновик снова равен сохранённому.
  const savedKey = `${savedMode}|${savedEnv}|${savedLifetime}|${savedEmail}`;
  const [prevSavedKey, setPrevSavedKey] = useState(savedKey);
  if (savedKey !== prevSavedKey) {
    setPrevSavedKey(savedKey);
    setMode(savedMode);
    setEnv(savedEnv);
    setLifetime(savedLifetime);
    setSendEmail(savedEmail);
  }

  const keysOf = (e: GoPayEnv): GoPayKeyState => gopay[e] ?? GOPAY_NO_KEYS;
  const isSet = (e: GoPayEnv, field: GoPaySecretField): boolean =>
    field === "api_key"
      ? Boolean(keysOf(e).api_key_set)
      : field === "api_secret"
        ? Boolean(keysOf(e).api_secret_set)
        : Boolean(keysOf(e).webhook_secret_set);
  const inFlight = (e: GoPayEnv): number =>
    Math.max(Number(gopay.in_flight?.[e]) || 0, Number(inFlightSeen[e]) || 0);
  const hasDraft = (e: GoPayEnv): boolean => GOPAY_SECRET_FIELDS.some((f) => secrets[e][f.key].trim() !== "");

  const dirty =
    mode !== savedMode ||
    env !== savedEnv ||
    lifetime.trim() !== savedLifetime ||
    sendEmail !== savedEmail ||
    hasDraft("test") ||
    hasDraft("live");
  const busy = saving || removing !== null;

  // ---------- кто сейчас видит QR ----------
  // Два выключателя: GoPay (effective) и окно выбора способа. QR — кнопка в
  // этом окне, поэтому без него «включённый» QR не видит никто.
  const effective = gopay.effective ?? { public: false, staff: false };
  const audience =
    kgsMode === "on" && effective.public
      ? "QR видят все покупатели"
      : kgsMode !== "off" && effective.staff
        ? "QR видят только сотрудники"
        : "QR не видит никто";
  const otherEnv: GoPayEnv = savedEnv === "test" ? "live" : "test";
  const otherEnvReady = keysOf(otherEnv).api_key_set && keysOf(otherEnv).api_secret_set;
  const unsettled = Number(gopay.unsettled) || 0;
  // Сбой неактивной среды важен, только пока по ней есть незакрытые счета.
  const healthEnvs = GOPAY_ENV_KEYS.filter(
    (e) => gopay.health?.[e]?.ok === false && (e === savedEnv || inFlight(e) > 0)
  );

  /** true — сохранено (или сохранять было нечего); false — отказ или ошибка в поле. */
  const save = async (): Promise<boolean> => {
    const patch: Record<string, unknown> = {};
    // Режим и среду шлём, только если их поменяли: наличие ключей сервер
    // проверяет лишь тогда, и сохранение одних ключей проходит всегда.
    if (mode !== savedMode) patch.mode = mode;
    if (env !== savedEnv) patch.env = env;
    if (lifetime.trim() !== savedLifetime) {
      const n = Number(lifetime.trim());
      if (!/^\d+$/.test(lifetime.trim()) || n < GOPAY_LIFETIME_MIN || n > GOPAY_LIFETIME_MAX) {
        setErr(`Срок жизни QR: целое число минут от ${GOPAY_LIFETIME_MIN} до ${GOPAY_LIFETIME_MAX}`);
        return false;
      }
      patch.lifetime_minutes = n;
    }
    if (sendEmail !== savedEmail) patch.send_buyer_email = sendEmail;
    for (const e of GOPAY_ENV_KEYS) {
      const part: Record<string, string> = {};
      for (const f of GOPAY_SECRET_FIELDS) {
        const value = secrets[e][f.key].trim();
        if (!value) continue;
        if (!GOPAY_SECRET_RE.test(value)) {
          // Само значение в текст ошибки не попадает.
          setErr(
            `${f.label} (${goPayEnvName(e)} среда): от 8 до 256 символов, только латиница, цифры и знаки, без пробелов`
          );
          return false;
        }
        part[f.key] = value;
      }
      if (Object.keys(part).length) patch[e] = part;
    }
    if (Object.keys(patch).length === 0) return true;

    setSaving(true);
    setErr(null);
    const res = await fetchData<Settings>("manage/settings/", "PATCH", { gopay: patch }, true);
    setSaving(false);
    if (res.ok && res.data) {
      onSaved(res.data);
      setSecrets(goPayEmptySecrets());
      setTests({});
      setFlash(true);
      setTimeout(() => setFlash(false), 2000);
      return true;
    }
    setErr(res.error || "Не удалось сохранить");
    return false;
  };

  const removeSecret = async (e: GoPayEnv, field: GoPaySecretField, label: string) => {
    const open = inFlight(e);
    const consequence =
      field === "webhook_secret"
        ? "Без него вебхуки GoPay не принимаются: оплата зачисляется только сверкой, с задержкой."
        : e === savedEnv
          ? "Без него единый QR перестанет показываться."
          : "";
    const question =
      open > 0
        ? `По этой среде есть незавершённые QR-счета (${open}). Без ключа оплаченный счёт не будет зачислен. Всё равно удалить?`
        : `Удалить «${label}» ${goPayEnvName(e, "gen")} среды? ${consequence}`.trim();
    if (!confirm(question)) return;

    const body: Record<string, unknown> = { [e]: { [field]: "" } };
    if (open > 0) body.force = true;
    setRemoving(`${e}.${field}`);
    setErr(null);
    const res = await fetchData<Settings>("manage/settings/", "PATCH", { gopay: body }, true);
    setRemoving(null);
    if (res.ok && res.data) {
      onSaved(res.data);
      setSecrets((prev) => ({ ...prev, [e]: { ...prev[e], [field]: "" } }));
      setInFlightSeen((prev) => ({ ...prev, [e]: 0 }));
      setTests((prev) => ({ ...prev, [e]: undefined }));
      setFlash(true);
      setTimeout(() => setFlash(false), 2000);
      return;
    }
    const refusal = res.data as unknown as { code?: string; count?: number } | null;
    if (res.status === 409 && refusal && typeof refusal === "object" && refusal.code === "gopay_in_flight") {
      setInFlightSeen((prev) => ({ ...prev, [e]: Math.max(1, Number(refusal.count) || 0) }));
    }
    setErr(res.error || "Не удалось удалить");
  };

  const runTest = async (e: GoPayEnv) => {
    setTesting(e);
    setTests((prev) => ({ ...prev, [e]: undefined }));
    const res = await fetchData<GoPayTestResult>("manage/settings/test-gopay/", "POST", { env: e }, true);
    setTesting(null);
    setTests((prev) => ({
      ...prev,
      [e]:
        res.ok && res.data && typeof res.data === "object"
          ? res.data
          : { ok: false, error: res.error || "Нет связи с сервером" },
    }));
    // Проверка меняет на сервере счётчик сбоев GoPay — перечитываем снимок,
    // чтобы красная строка о сбое не висела после удачной проверки.
    const snapshot = await fetchData<Settings>("manage/settings/", "GET", null, true);
    if (snapshot.ok && snapshot.data?.gopay) onSaved(snapshot.data);
  };

  // Кнопка «Сохранить» всей секции стоит в её шапке, далеко от полей ключей:
  // человек вставлял ключи, жал «Проверить соединение» рядом и получал «не
  // заданы». Поэтому кнопка у самих полей сначала сохраняет введённое.
  const saveAndTest = async (e: GoPayEnv) => {
    if (!(await save())) return;
    await runTest(e);
  };

  const copyWebhook = async () => {
    const ok = await goPayCopy(gopay.webhook_url);
    setCopied(ok ? "ok" : "fail");
    setTimeout(() => setCopied(null), 2000);
  };

  const modeLabel = GOPAY_MODES.find((m) => m.value === savedMode)?.label || savedMode;
  const chip = (on: boolean) =>
    `rounded-lg border px-3 py-1.5 text-xs transition-colors ${
      on ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:text-foreground"
    }`;

  return (
    <section className="rounded-2xl border border-border bg-surface p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <FiGrid className="h-4 w-4 text-accent" />
          <h2 className="text-base font-semibold">Единый QR (GoPay)</h2>
        </div>
        <div className="flex items-center gap-3">
          {flash && <SavedFlash />}
          {dirty && (
            <button
              onClick={save}
              disabled={busy}
              className="rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {saving ? "Сохранение…" : "Сохранить"}
            </button>
          )}
        </div>
      </div>
      <p className="mt-1 text-xs text-muted-2">
        Сейчас: <span className="text-foreground">{modeLabel}</span> · среда:{" "}
        <span className="text-foreground">{savedEnv === "test" ? "ТЕСТ" : "БОЕВАЯ"}</span> ·{" "}
        <span className="text-foreground">{audience}</span>
      </p>
      <p className="mt-1 text-xs text-muted-2">
        Покупатель платит по QR любым банком Кыргызстана на нашей странице. Кредиты начисляются только после
        подтверждения оплаты самим GoPay. Менять режим, среду и ключи может только главный администратор.
      </p>

      {savedEnv === "test" && (
        <div className="mt-3 rounded-xl border border-status-wait/50 bg-status-wait/10 px-3 py-2 text-sm font-semibold text-status-wait">
          ТЕСТОВАЯ СРЕДА: QR видят только сотрудники, деньги не списываются, платежи помечаются «тест» и не
          попадают в выручку
        </div>
      )}

      {healthEnvs.map((e) => {
        const h = gopay.health?.[e];
        if (!h) return null;
        const since = goPaySince(h.since);
        const text =
          // Среду называем, только когда сбоит не та, что сейчас включена.
          (e !== savedEnv ? `${e === "test" ? "Тестовая" : "Боевая"} среда: ` : "") +
          `GoPay не отвечает / отклоняет запросы${since ? ` с ${since}` : ""}` +
          ` (${GOPAY_HEALTH_KIND[h.kind] || h.kind || "сбой"}` +
          `${h.code && h.code !== h.kind ? `, код ${h.code}` : ""}, подряд: ${Number(h.fails) || 0})` +
          (h.kind === "auth" ? " — проверьте ключ, секрет и ограничение по IP" : "") +
          (h.kind === "org_inactive" ? " — организация не активирована" : "") +
          (h.down ? ". Запросы к GoPay временно приостановлены" : "");
        return (
          <p key={e} className="mt-3 text-sm text-status-fail">
            {text}
          </p>
        );
      })}

      {err && <div className="mt-3 text-sm text-status-fail">{err}</div>}

      {unsettled > 0 && (
        <p className="mt-3 text-sm text-status-fail">
          <Link href="/admin-new/payments?unsettled=1" className="font-semibold underline underline-offset-2">
            Оплачено, но не зачислено: {unsettled}
          </Link>
        </p>
      )}

      {effective.public && kgsMode !== "on" && (
        <p className="mt-3 text-xs text-status-wait">
          QR включён, но окно выбора способа открыто не всем — включите «Оплата в сомах: выбор способа»
        </p>
      )}
      {effective.staff && !effective.public && kgsMode === "off" && (
        <p className="mt-3 text-xs text-status-wait">
          QR готов для сотрудников, но окно выбора способа выключено — включите «Оплата в сомах: выбор способа»
          хотя бы для сотрудников
        </p>
      )}
      {!gopay.configured && otherEnvReady && (
        <p className="mt-3 text-xs text-status-wait">
          Ключи сохранены для {goPayEnvName(otherEnv, "gen")} среды, а активна {goPayEnvName(savedEnv)} —
          переключите среду, иначе QR никому не показывается
        </p>
      )}
      {!gopay.configured && !otherEnvReady && savedMode !== "off" && (
        <p className="mt-3 text-xs text-muted-2">
          Для {goPayEnvName(savedEnv, "gen")} среды не заданы API-ключ и секрет — пока их нет, QR никому не
          показывается.
        </p>
      )}

      {/* Режим */}
      <div className="mt-4 flex flex-wrap gap-2">
        {GOPAY_MODES.map((m) => (
          <button key={m.value} onClick={() => setMode(m.value)} title={m.hint} className={chip(mode === m.value)}>
            {m.label}
          </button>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-muted-2">{GOPAY_MODES.find((m) => m.value === mode)?.hint}</p>

      {/* Среда и срок жизни */}
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted">Среда — какая пара ключей работает</span>
          <div className="flex flex-wrap gap-2">
            {GOPAY_ENVS.map((item) => (
              <button
                key={item.value}
                onClick={() => setEnv(item.value)}
                title={item.hint}
                className={chip(env === item.value)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <span className="text-[11px] text-muted-2">{GOPAY_ENVS.find((item) => item.value === env)?.hint}</span>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="gopay-lifetime" className="text-xs text-muted">
            Срок жизни QR, минут
          </label>
          <input
            id="gopay-lifetime"
            type="number"
            inputMode="numeric"
            min={GOPAY_LIFETIME_MIN}
            max={GOPAY_LIFETIME_MAX}
            step={1}
            value={lifetime}
            onChange={(e) => setLifetime(e.target.value)}
            className={`${INPUT} max-w-[10rem]`}
          />
          <span className="text-[11px] text-muted-2">
            От {GOPAY_LIFETIME_MIN} до {GOPAY_LIFETIME_MAX}. Столько покупатель видит QR и таймер; действует на
            новые счета.
          </span>
        </div>
      </div>

      <label className="mt-4 flex max-w-xl cursor-pointer items-start gap-3 rounded-xl border border-border bg-surface-2 px-3 py-2.5">
        <input
          type="checkbox"
          checked={sendEmail}
          onChange={(e) => setSendEmail(e.target.checked)}
          className="mt-0.5 h-4 w-4 accent-[var(--accent)]"
        />
        <span className="flex flex-col gap-0.5">
          <span className="text-sm text-foreground">Передавать e-mail покупателя в GoPay</span>
          <span className="text-[11px] text-muted-2">
            Без него страница оплаты GoPay сначала спрашивает у покупателя контакт, а чек онлайн-кассы уходит
            без получателя. Тот же e-mail уже передаётся в Freedom Pay. Выключите, если передавать нельзя.
          </span>
          <span className="text-[11px] text-muted-2">
            У аккаунтов без настоящей почты (вход только через Telegram) e-mail не передаётся при любом
            положении галочки.
          </span>
        </span>
      </label>

      {/* Ключи: две среды */}
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {GOPAY_ENV_KEYS.map((e) => {
          const test = tests[e];
          const open = inFlight(e);
          return (
            <div key={e} className="rounded-xl border border-border p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <FiKey className="h-4 w-4 text-accent" />
                  <h3 className="text-sm font-semibold">{e === "test" ? "Тестовые ключи" : "Боевые ключи"}</h3>
                  {e === savedEnv && (
                    <span className="rounded border border-accent/40 px-1.5 py-0.5 text-[10px] text-accent">
                      активная среда
                    </span>
                  )}
                </div>
                <button
                  onClick={() => (hasDraft(e) ? saveAndTest(e) : runTest(e))}
                  disabled={testing !== null || busy}
                  className={
                    hasDraft(e)
                      ? "rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50"
                      : "rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-xs font-semibold text-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
                  }
                >
                  {saving && hasDraft(e)
                    ? "Сохранение…"
                    : testing === e
                      ? "Проверка…"
                      : hasDraft(e)
                        ? "Сохранить и проверить"
                        : "Проверить соединение"}
                </button>
              </div>

              <div className="mt-3 flex flex-col gap-3">
                {GOPAY_SECRET_FIELDS.map((f) => {
                  const set = isSet(e, f.key);
                  const tail = f.key === "api_key" ? String(keysOf(e).api_key_tail || "") : "";
                  const inputId = `gopay-${e}-${f.key}`;
                  return (
                    <div key={f.key} className="flex flex-col gap-1">
                      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                        <label htmlFor={inputId} className="text-xs text-muted">
                          {f.label}:{" "}
                          <span className={set ? "text-status-ok" : "text-muted-2"}>
                            {set ? (tail ? `задан · ${tail}` : "задан") : "не задан"}
                          </span>
                        </label>
                        {set && (
                          <button
                            type="button"
                            onClick={() => removeSecret(e, f.key, f.label)}
                            disabled={busy}
                            className="text-[11px] text-muted-2 underline underline-offset-2 transition-colors hover:text-status-fail disabled:opacity-50"
                          >
                            {removing === `${e}.${f.key}` ? "Удаление…" : "Удалить"}
                          </button>
                        )}
                      </div>
                      <input
                        id={inputId}
                        name={inputId}
                        type="password"
                        value={secrets[e][f.key]}
                        onChange={(ev) =>
                          setSecrets((prev) => ({ ...prev, [e]: { ...prev[e], [f.key]: ev.target.value } }))
                        }
                        placeholder={set ? "новое значение заменит текущее" : "вставьте значение"}
                        autoComplete="new-password"
                        spellCheck={false}
                        className={`${INPUT} w-full font-mono`}
                      />
                    </div>
                  );
                })}
              </div>

              {open > 0 && (
                <p className="mt-3 text-[11px] text-status-wait">
                  Незавершённых QR-счетов по этой среде: {open}. Пока они не закрыты, ключи не удаляйте — без них
                  оплаченный счёт не будет зачислен.
                </p>
              )}
              {hasDraft(e) && (
                <p className="mt-3 text-[11px] text-muted-2">
                  Введённые значения ещё не сохранены. Нажмите «Сохранить и проверить» выше — после сохранения поля
                  очистятся, а рядом с названием появится «задан».
                </p>
              )}

              {test && (
                <div className={`mt-3 text-sm ${test.ok ? "text-status-ok" : "text-status-fail"}`}>
                  {test.ok
                    ? `Ключ и секрет приняты · приложений банков: ${test.apps ?? "—"}` +
                      (test.webhook_secret_set === false ? " · ВНИМАНИЕ: не задан секрет вебхуков" : "")
                    : test.error || "GoPay отклонил запрос"}
                </div>
              )}
              <p className="mt-3 text-[11px] text-muted-2">
                Проверка не различает тестовый и боевой ключ и не показывает, активирована ли организация в
                GoPay, — это покажет первый QR
              </p>
            </div>
          );
        })}
      </div>

      {/* Вебхуки: что перенести в кабинет GoPay */}
      <div className="mt-5 border-t border-border pt-4">
        <h3 className="text-sm font-semibold">Вебхуки — что указать в кабинете GoPay</h3>
        {gopay.webhook_url ? (
          <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
            <input
              type="text"
              readOnly
              value={gopay.webhook_url}
              onFocus={(e) => e.currentTarget.select()}
              aria-label="Адрес вебхуков GoPay"
              className={`${INPUT} min-w-0 flex-1 font-mono text-xs`}
            />
            <button
              type="button"
              onClick={copyWebhook}
              className="shrink-0 rounded-lg border border-border bg-surface-2 px-3 py-2 text-xs font-semibold text-foreground transition-opacity hover:opacity-90"
            >
              {copied === "ok" ? "Скопировано" : copied === "fail" ? "Выделите и скопируйте вручную" : "Скопировать"}
            </button>
          </div>
        ) : (
          <p className="mt-2 text-sm text-status-wait">Не задан SITE_BASE_URL на сервере</p>
        )}
        <p className="mt-3 text-xs text-muted">
          Кабинет GoPay → Developer → Webhooks: вставьте этот адрес и отметьте события. Те, что не отмечены,
          GoPay не присылает.
        </p>
        <ul className="mt-2 flex flex-col gap-1 text-xs">
          {(gopay.webhook_events || []).map((name) => (
            <li key={name} className="flex flex-wrap items-baseline gap-x-2">
              <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono">{name}</code>
              <span className="text-status-ok">обязательно</span>
            </li>
          ))}
          {(gopay.webhook_events_optional || []).map((name) => (
            <li key={name} className="flex flex-wrap items-baseline gap-x-2">
              <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono">{name}</code>
              <span className="text-muted-2">
                включите, если в кабинете включена онлайн-касса — иначе чеки в журнал не попадут
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-[11px] text-muted-2">Поле callback_url в кабинете GoPay оставьте пустым.</p>
        <p className="mt-1 text-[11px] text-muted-2">
          Если «Отправить тест» в кабинете показывает 403, 5xx или таймаут — запрос не дошёл до сайта
          (Cloudflare/WAF), секрет тут ни при чём; 400 — неверный секрет.
        </p>
        {gopay.api_host && (
          <p className="mt-1 text-[11px] text-muted-2">
            Запросы к GoPay уходят на <span className="font-mono">{gopay.api_host}</span>.
          </p>
        )}
      </div>
    </section>
  );
}

type KgsMode = "off" | "staff" | "on";

const KGS_MODES: { value: KgsMode; label: string; hint: string }[] = [
  { value: "off", label: "Выключено", hint: "выбора нет: «Пополнить» сразу ведёт на страницу Freedom Pay, как раньше" },
  { value: "staff", label: "Только сотрудникам", hint: "для проверки способов перед запуском; остальные платят как раньше" },
  { value: "on", label: "Включено", hint: "выбор способа видят все" },
];

/** Подписи способов в админке. Единый QR здесь не галочка: он включается блоком GoPay. */
const KGS_METHOD_LABELS: Record<string, string> = {
  elqr: "Единый QR",
  mbank: "MBANK",
  odengi: "О!Деньги",
  balance: "Balance.kg",
  megapay: "MegaPay",
  card: "Карта",
};

const KGS_METHODS_FALLBACK = ["elqr", "mbank", "odengi", "balance", "megapay", "card"];
// То же правило, что на сервере: код уходит в Freedom Pay как есть.
const KGS_ELQR_CODE_RE = /^[A-Za-z0-9_]{3,32}$/;

/** «a, b,elqr» → ["a", "b"]: единый QR в списке галочек не участвует. */
const kgsEnabledList = (raw?: string): string[] =>
  String(raw || "")
    .split(",")
    .map((k) => k.trim())
    .filter((k) => k && k !== "elqr");

/**
 * Оплата в сомах: окно выбора способа перед оплатой. Режим off/staff/on и
 * какие способы Freedom Pay показывать. Единый QR в это окно добавляет блок
 * GoPay выше; код единого QR от Freedom Pay остался полем на будущее.
 */
function KgsMethodsSection({ settings, onSaved }: { settings: Settings; onSaved: (s: Settings) => void }) {
  const known = (settings.kgs_methods_known?.length ? settings.kgs_methods_known : KGS_METHODS_FALLBACK).filter(
    (k) => k !== "elqr"
  );
  const savedMode: KgsMode = settings.kgs_methods_mode ?? "off";
  const savedEnabled = known.filter((k) => kgsEnabledList(settings.kgs_methods_enabled).includes(k));
  const savedCode = String(settings.kgs_elqr_ps_code || "");

  const [mode, setMode] = useState<KgsMode>(savedMode);
  const [enabled, setEnabled] = useState<string[]>(savedEnabled);
  const [code, setCode] = useState(savedCode);
  const [saving, setSaving] = useState(false);
  const [flash, setFlash] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // Сохранили (или перечитали настройки) — черновик снова равен сохранённому.
  const savedKey = `${savedMode}|${savedEnabled.join(",")}|${savedCode}`;
  const [prevSavedKey, setPrevSavedKey] = useState(savedKey);
  if (savedKey !== prevSavedKey) {
    setPrevSavedKey(savedKey);
    setMode(savedMode);
    setEnabled(savedEnabled);
    setCode(savedCode);
  }

  // Порядок галочек не важен — сравниваем и отправляем в порядке показа.
  const enabledOrdered = known.filter((k) => enabled.includes(k));
  const codeTrimmed = code.trim();
  const dirty =
    mode !== savedMode || enabledOrdered.join(",") !== savedEnabled.join(",") || codeTrimmed !== savedCode;
  // Одна «карта» — не выбор. Единый QR считается, только если GoPay готов показать
  // его хотя бы сотрудникам; код Freedom Pay кнопку больше не даёт.
  const onlyCard = enabledOrdered.every((k) => k === "card") && !settings.gopay?.effective?.staff;

  const save = async () => {
    const patch: Record<string, string> = {};
    if (mode !== savedMode) patch.kgs_methods_mode = mode;
    if (enabledOrdered.join(",") !== savedEnabled.join(",")) patch.kgs_methods_enabled = enabledOrdered.join(",");
    if (codeTrimmed !== savedCode) {
      if (codeTrimmed && !KGS_ELQR_CODE_RE.test(codeTrimmed)) {
        setErr("Код единого QR: латинские буквы, цифры и «_», от 3 до 32 символов. Чтобы убрать код, оставьте поле пустым.");
        return;
      }
      patch.kgs_elqr_ps_code = codeTrimmed;
    }
    if (Object.keys(patch).length === 0) return;
    setSaving(true);
    setErr(null);
    const res = await fetchData<Settings>("manage/settings/", "PATCH", patch, true);
    setSaving(false);
    if (res.ok && res.data) {
      onSaved(res.data);
      setFlash(true);
      setTimeout(() => setFlash(false), 2000);
    } else {
      setErr(res.error || "Не удалось сохранить");
    }
  };

  return (
    <section className="rounded-2xl border border-border bg-surface p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <FiCreditCard className="h-4 w-4 text-accent" />
          <h2 className="text-base font-semibold">Оплата в сомах: выбор способа</h2>
        </div>
        <div className="flex items-center gap-3">
          {flash && <SavedFlash />}
          {dirty && (
            <button
              onClick={save}
              disabled={saving}
              className="rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {saving ? "Сохранение…" : "Сохранить"}
            </button>
          )}
        </div>
      </div>
      <p className="mt-1 text-xs text-muted-2">
        Перед уходом на страницу Freedom Pay человек выбирает у нас, чем платить: через приложение банка или
        картой — и попадает сразу на нужный способ, а не на общий список. Деньги, зачисление и сверка идут как
        раньше.
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        {KGS_MODES.map((m) => (
          <button
            key={m.value}
            onClick={() => setMode(m.value)}
            title={m.hint}
            className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
              mode === m.value
                ? "border-accent bg-accent/10 text-accent"
                : "border-border text-muted hover:text-foreground"
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-muted-2">{KGS_MODES.find((m) => m.value === mode)?.hint}</p>

      <div className="mt-4">
        <div className="text-xs text-muted">Способы в окне выбора</div>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
          {known.map((k) => (
            <label key={k} className="inline-flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={enabled.includes(k)}
                onChange={(e) =>
                  setEnabled((prev) => (e.target.checked ? [...prev, k] : prev.filter((x) => x !== k)))
                }
                className="h-4 w-4 accent-accent"
              />
              {KGS_METHOD_LABELS[k] || k}
            </label>
          ))}
        </div>
        {onlyCard && (
          <p className="mt-2 text-[11px] text-status-wait">
            Без единого QR (GoPay) окно выбора не показывается: с одной кнопкой «картой» выбирать не из
            чего.
          </p>
        )}
      </div>

      <div className="mt-4 flex max-w-sm flex-col gap-1">
        <label className="text-xs text-muted">Код единого QR Freedom Pay (не используется)</label>
        <input
          type="text"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="пусто — кода пока нет"
          autoComplete="off"
          spellCheck={false}
          className={`${INPUT} font-mono`}
        />
        <span className="text-[11px] text-muted-2">
          Единый QR работает через GoPay (блок выше). Код Freedom Pay хранится на будущее и кнопку не включает.
        </span>
      </div>

      {err && <div className="mt-3 text-sm text-red-400">{err}</div>}
    </section>
  );
}
