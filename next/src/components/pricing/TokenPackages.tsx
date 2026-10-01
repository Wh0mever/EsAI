"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import dynamic from "next/dynamic";
import { fetchData } from "@/tools/fetchData";
import { FiZap, FiGift } from "react-icons/fi";
import Cookies from "js-cookie";
import { formatPrice } from "@/lib/currency";
import type { Currency, KgsMethodKey } from "@/lib/currency";
import { refreshKgsMethods, useKgsMethods } from "@/hooks/useCurrency";
import { apiLang } from "@/lib/apiLang";
import { trackFunnel } from "@/tools/funnel";
import { useCryptoCurrencies } from "@/hooks/useCryptoCurrencies";
import { readCryptoSession } from "@/lib/cryptoSession";
import CryptoPendingBanner from "@/components/payments/crypto/CryptoPendingBanner";
import KgsMethodModal from "@/components/payments/KgsMethodModal";
import type { KgsHeldDiscount } from "@/components/payments/KgsMethodModal";
import type { PendingPayment } from "@/types/crypto";

// Экран криптооплаты тянет за собой QR и значки монет — грузим его только
// тому, кто действительно выбрал крипту.
const CryptoCheckoutModal = dynamic(
  () => import("@/components/payments/crypto/CryptoCheckoutModal"),
  { ssr: false }
);

type Pkg = {
  id: number | string;
  name: string;
  tokens: number;
  bonus_tokens?: number;
  price: number;
  currency: string;
  sort_order?: number;
  description?: string;
  /** маркетинговая плашка над пакетом (из админки), напр. «⭐ Популярный» */
  badge?: string;
  /** визуально выделить пакет как рекомендованный (из админки) */
  featured?: boolean;
};

/**
 * "Сколько хватит" — приходит отдельным публичным эндпоинтом
 * (GET /api/plans/packages/value/, core/plans/credit_value.py), НЕ связан
 * с денежным GET /api/plans/packages/ и НЕ влияет на него. Категория может
 * отсутствовать (нет эталонной модели) — рендерим только то, что пришло.
 * Музыка сознательно не подключена (решено с клиентом).
 */
type ValueCategory = {
  count: number;
  unit_model_name?: string;
};

type PackageValue = {
  text?: ValueCategory;
  image?: ValueCategory;
  video?: ValueCategory;
  document?: ValueCategory;
};

type PkgWithValue = {
  id: number | string;
  value?: PackageValue;
};

type TokenPackagesProps = {
  /** активный процент exit-discount (useExitDiscount().active), если скидка подтверждена claim-ом */
  discountPercent?: number | null;
  /** заголовок X-Device-Key — прокидывается в purchase/, чтобы бэк мог смёрджить гостевой claim */
  deviceKey?: string;
  /**
   * Отображаемая валюта (переключатель KGS/RUB на /pricing, см.
   * next/src/hooks/useCurrency.ts) — ТОЛЬКО для показа цены, TokenPackage.price
   * на бэкенде всегда в сомах. По умолчанию "KGS" (без пересчёта), если
   * родитель не подключил переключатель валют.
   */
  currency?: Currency;
  /** Пересчёт цены из сомов в currency по курсу с бэкенда — identity по умолчанию. */
  convert?: (priceKgs: number) => number;
  /** Готовая подпись цены с валютой («1 900 сом», «$21.66») — из useCurrency(). */
  format?: (priceKgs: number, somLabel?: string) => string;
  /** вызывается сразу при клике "Купить", до похода на бэк — сигнал для useExitDiscount не показывать попап во время оплаты */
  onPurchaseStart?: () => void;
  /** вызывается после ответа/редиректа покупки (успех или ошибка) */
  onPurchaseEnd?: () => void;
  /**
   * Куда вернуть человека после оплаты и после входа. По умолчанию профиль и
   * /pricing. Студия ставит сюда «/studio»: тот, кто пошёл платить из
   * недоделанного мультфильма, должен вернуться к нему, а не в профиль.
   */
  returnTo?: string;
  /**
   * Чем заменить блок «Примерно хватит на». Нужно витрине студии: там
   * считают не запросы и картинки, а сцены и мультфильмы.
   */
  valueOverride?: (pkg: Pkg) => { title: string; rows: string[] } | null;
};

/**
 * TokenPackages — full-page token top-up packages for the /pricing route.
 * Shares the same backend contract as the chat TopUpModal:
 *  - GET  /api/plans/packages/  (public)  -> Pkg[]
 *  - POST /api/plans/purchase/  (auth)    -> { redirect_url, order_id, amount, currency }
 *
 * Guests are routed to /auth/signin (with ?next=/pricing) instead of purchasing.
 * Pay-as-you-go tokens, KGS pricing — no subscriptions, no music.
 *
 * Additionally fetches GET /api/plans/packages/value/ (public, independent
 * request) to render a "Примерно хватит на" block per card — merged by id.
 * This second fetch is purely additive: it never gates loading/error state
 * and never touches price/discount/purchase logic above.
 */
export default function TokenPackages({
  discountPercent = null,
  deviceKey,
  currency = "KGS",
  convert = (priceKgs: number) => priceKgs,
  format,
  onPurchaseStart,
  onPurchaseEnd,
  returnTo,
  valueOverride,
}: TokenPackagesProps = {}) {
  const { t, i18n } = useTranslation("common");
  // Названия и подписи пакетов лежат в базе на трёх языках (админка),
  // поэтому язык уезжает на сервер вместе с запросом.
  const lang = apiLang(i18n.language);
  const [packages, setPackages] = useState<Pkg[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [buyingId, setBuyingId] = useState<string | number | null>(null);
  const [authed, setAuthed] = useState(false);
  // "Хватит на" — второй, независимый fetch. Намеренно НЕ участвует в
  // loading/error денежного состояния выше: если он упадёт или придёт
  // пустым, просто не рендерим доп.блок — покупка (цена/кнопка) должна
  // работать в любом случае.
  const [valueById, setValueById] = useState<Record<string, PackageValue>>({});
  // Незавершённая оплата. Разбор воронки показал, что половина брошенных
  // платежей — это повторные нажатия одних и тех же людей: страница оплаты
  // закрылась, и продолжить было нечем, кроме как начать заново.
  const [pending, setPending] = useState<PendingPayment | null>(null);
  const [pendingHidden, setPendingHidden] = useState(false);
  // Крипта: список монет и открытый экран оплаты.
  const crypto = useCryptoCurrencies();
  const [checkout, setCheckout] = useState<
    { pkg: Pkg | null; resumeOrderId?: string } | null
  >(null);
  // Оплата в сомах: окно «банк или карта» перед уходом на страницу Freedom Pay.
  // Пустой список способов — выбора нет, «Пополнить» работает как раньше.
  const kgsMethods = useKgsMethods();
  const [kgsPick, setKgsPick] = useState<Pkg | null>(null);
  const [kgsBusy, setKgsBusy] = useState<KgsMethodKey | null>(null);
  const [kgsError, setKgsError] = useState("");
  // Скидка «при уходе» закреплена за оплатой, начатой другим способом.
  const [kgsHeld, setKgsHeld] = useState<KgsHeldDiscount | null>(null);
  // Номер «сеанса» окна выбора: закрыли окно — ответ на запрос, начатый в
  // нём, уже никуда не ведёт (ни на страницу банка, ни в текст ошибки).
  const kgsSession = useRef(0);

  useEffect(() => {
    setAuthed(Boolean(Cookies.get("access")));
  }, []);

  // Вернулись со страницы банка кнопкой «назад»: браузер может поднять
  // страницу из памяти как была — с крутящейся кнопкой способа. Снимаем её,
  // иначе выбрать другой способ можно было бы, только закрыв окно.
  useEffect(() => {
    const onShow = (e: PageTransitionEvent) => {
      if (e.persisted) setKgsBusy(null);
    };
    window.addEventListener("pageshow", onShow);
    return () => window.removeEventListener("pageshow", onShow);
  }, []);

  useEffect(() => {
    if (!authed) return;
    let alive = true;
    (async () => {
      const res = await fetchData<{ pending: PendingPayment | null }>(
        "plans/purchase/pending/", "GET", null, true
      );
      if (!alive) return;
      if (res.ok && res.data?.pending) {
        setPending(res.data.pending);
        return;
      }
      // Сервер не знает о счёте (например, ответ не успел дойти до перезагрузки) —
      // подстраховываемся памятью вкладки: номер заказа хватит, чтобы открыть
      // тот же экран.
      const saved = readCryptoSession();
      if (saved) {
        setPending({
          kind: "crypto", order_id: saved.order_id, amount: "", currency: "USD",
          package: saved.package_name || "", redirect_url: null,
          status_url: `/api/plans/purchase/crypto/${saved.order_id}/`,
          coin: saved.coin || "", network: saved.network || "",
          pay_amount: "", amount_remaining: "", expires_at: null,
          created_at: new Date(saved.saved_at).toISOString(),
        });
      }
    })();
    return () => {
      alive = false;
    };
  }, [authed]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchData<{ packages: PkgWithValue[] }>(
          `plans/packages/value/?lang=${lang}`,
          "GET",
          null,
          false
        );
        if (cancelled) return;
        const list = Array.isArray(res?.data?.packages) ? res.data!.packages : [];
        if (res?.ok && list.length) {
          const map: Record<string, PackageValue> = {};
          for (const item of list) {
            if (item && item.value) map[String(item.id)] = item.value;
          }
          setValueById(map);
        }
      } catch {
        // тихо игнорируем — доп.блок просто не покажется
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [lang]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    (async () => {
      try {
        const res = await fetchData<Pkg[]>(`plans/packages/?lang=${lang}`, "GET", null, false);
        if (cancelled) return;
        if (res?.ok && Array.isArray(res.data)) {
          const list = [...res.data].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
          setPackages(list);
        } else setError(t("topup.load_error", { defaultValue: "Не удалось загрузить пакеты" }));
      } catch {
        if (!cancelled) setError(t("topup.load_error", { defaultValue: "Не удалось загрузить пакеты" }));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t, lang]);

  const onBuy = async (pkg: Pkg) => {
    // Считаем НАЖАТИЕ, а не созданный платёж: между ними отсеиваются гости,
    // которых уводит на вход, и именно этот разрыв нам и нужно видеть.
    trackFunnel("topup_click", { package_id: pkg.id, currency, authed });
    // Guests must authenticate before topping up.
    if (!authed) {
      const next = encodeURIComponent(returnTo || "/pricing");
      window.location.href = `/auth/signin?next=${next}`;
      return;
    }
    // Крипта: вместо ухода на страницу банка открываем свой экран оплаты.
    if (currency === "USD") {
      // Список монет ещё не пришёл или метод закрыт — молча увести человека
      // на страницу банка в сомах нельзя: он выбрал крипту.
      if (!crypto.enabled) {
        setError(t("crypto.no_coins", { defaultValue: "Монеты пока недоступны. Попробуйте позже." }));
        return;
      }
      onPurchaseStart?.();
      setCheckout({ pkg });
      return;
    }
    // Сомы: сначала спрашиваем, чем удобнее платить — банком или картой.
    if (currency !== "RUB" && kgsMethods.length > 0) {
      openKgsChooser(pkg);
      return;
    }
    await startCardPurchase(pkg, currency === "RUB" ? "RUB" : "KGS");
  };

  const openKgsChooser = (pkg: Pkg) => {
    // Пока окно открыто, попап скидки «при уходе» поверх него не нужен.
    onPurchaseStart?.();
    setError("");
    setKgsError("");
    setKgsHeld(null);
    setKgsBusy(null);
    setKgsPick(pkg);
  };

  const closeKgsChooser = () => {
    kgsSession.current += 1;
    setKgsPick(null);
    setKgsBusy(null);
    setKgsError("");
    setKgsHeld(null);
    onPurchaseEnd?.();
  };

  const onKgsPick = (method: KgsMethodKey) => {
    if (!kgsPick) return;
    trackFunnel("kgs_method_pick", { package_id: kgsPick.id, method });
    void startCardPurchase(kgsPick, "KGS", method);
  };

  // Способ выбирают для оплаты в сомах — и сумма в окне всегда в сомах, даже
  // если на витрине сейчас доллары (сюда приходят и из окна крипты, кнопкой
  // «Карта · сом»). Скидка «при уходе» на сомовую оплату действует всегда.
  const kgsPriceLabel = (pkg: Pkg): string => {
    const price = Number(pkg.price) || 0;
    const toPay = discountPercent
      ? Math.round(price * (1 - discountPercent / 100) * 100) / 100
      : price;
    return formatPrice(toPay, "KGS", t("topup.som", { defaultValue: "сом" }));
  };

  const somLabel = (amount: unknown): string =>
    formatPrice(Number(amount) || 0, "KGS", t("topup.som", { defaultValue: "сом" }));

  /**
   * Текст ошибки оплаты картой. Бэкенд отвечает кодами (yookassa_config_missing,
   * currency_rate_invalid, package_not_found…) или сырым текстом банка — раньше
   * всё это показывалось человеку как есть. Как и у крипты, переводим в
   * понятные слова.
   */
  const cardPurchaseError = (status?: number, code?: string): string => {
    if (status === 401) {
      return t("crypto.err_unauthorized", {
        defaultValue: "Сессия истекла. Войдите снова, чтобы продолжить.",
      });
    }
    if (code === "method_unavailable") {
      // Способ выключили, пока окно выбора было открыто.
      return t("kgspay.err_method_unavailable", {
        defaultValue: "Этот способ сейчас недоступен. Выберите другой.",
      });
    }
    if (code === "package_not_found" || code === "package_not_payable") {
      return t("topup.err_package_unavailable", {
        defaultValue: "Этот пакет сейчас недоступен. Обновите страницу и выберите пакет снова.",
      });
    }
    return t("topup.err_payment_unavailable", {
      defaultValue:
        "Не удалось открыть страницу оплаты. Попробуйте ещё раз через минуту или выберите другой способ оплаты.",
    });
  };

  /**
   * Оплата картой: уходим на страницу банка. Валюта решает, какого.
   * method — способ, выбранный в окне оплаты сомами (только KGS): с ним
   * страница Freedom Pay открывается сразу на нужном банке или на карте.
   */
  const startCardPurchase = async (
    pkg: Pkg,
    payCurrency: "KGS" | "RUB",
    method?: KgsMethodKey,
    // Человек согласился платить этим способом без скидки (блок «скидка
    // закреплена за другой оплатой» в окне выбора).
    fullPrice = false
  ) => {
    if (buyingId != null) return;
    // Ошибку показываем там, куда человек сейчас смотрит: в окне выбора
    // способа или на самой странице.
    const fail = (text: string) => (method ? setKgsError(text) : setError(text));
    // Окно выбора закрыли, пока шёл запрос: человек передумал, и уводить его
    // на страницу банка или показывать ошибку уже некуда. Сам платёж остаётся
    // на сервере — к нему вернёт повторный клик или баннер «продолжить оплату».
    const session = kgsSession.current;
    const dismissed = () => Boolean(method) && session !== kgsSession.current;
    // Выбор способа выключили, пока вкладка была открыта: платим как раньше,
    // без способа, — уже после того, как этот запрос отпустит кнопки.
    let retryPlain = false;
    // Уходим на страницу банка — кнопка способа крутится до самого перехода,
    // чтобы за эти полсекунды нельзя было создать второй платёж другим способом.
    let leaving = false;
    setBuyingId(pkg.id);
    setError("");
    if (method) {
      setKgsBusy(method);
      setKgsError("");
      setKgsHeld(null);
    }
    onPurchaseStart?.();
    try {
      const res = await fetchData<any>(
        "plans/purchase/",
        "POST",
        // Валюта решает платёжный путь: RUB -> ЮKassa, KGS -> FreedomPay.
        {
          package_id: pkg.id,
          pay_currency: payCurrency,
          ...(method ? { method } : {}),
          ...(method && fullPrice ? { full_price: true } : {}),
          ...(returnTo ? { return_to: returnTo } : {}),
        },
        true,
        deviceKey ? { "X-Device-Key": deviceKey } : undefined
      );
      if (dismissed()) return;
      if (!res?.ok) {
        if (method && res?.error === "method_unavailable") {
          // Список способов во вкладке устарел (его меняют в админке без
          // выкладки). Берём свежий: если выбора больше нет — платим как
          // раньше; если есть — окно перерисуется с тем, что доступно.
          const fresh = await refreshKgsMethods();
          if (dismissed()) return;
          if (fresh.length === 0) {
            retryPlain = true;
            return;
          }
        }
        const heldUrl = res?.data?.held?.redirect_url;
        if (method && res?.error === "discount_held" && typeof heldUrl === "string" && heldUrl) {
          // Скидка занята оплатой, начатой другим способом: сумму молча не
          // меняем, а даём выбрать — продолжить ту оплату или платить без скидки.
          setKgsHeld({
            method,
            heldMethod: String(res.data.held.method || ""),
            heldPriceLabel: somLabel(res.data.held.amount),
            fullPriceLabel: somLabel(res.data.amount),
            redirectUrl: heldUrl,
          });
          return;
        }
        fail(cardPurchaseError(res?.status, res?.error));
        return;
      }
      const d = res.data || {};
      const url = d.redirect_url || d.payment_url || d.url || d.checkout_url;
      if (url && typeof url === "string") {
        leaving = true;
        window.location.href = url;
        return;
      }
      // No payment URL (e.g. instant credit / sandbox) — nudge balance listeners.
      try {
        window.dispatchEvent(new CustomEvent("balance:refresh"));
      } catch {}
      if (method) closeKgsChooser();
    } catch {
      if (!dismissed()) {
        fail(t("topup.purchase_error", { defaultValue: "Не удалось начать оплату" }));
      }
    } finally {
      setBuyingId(null);
      if (method) {
        // Окно выбора ещё открыто: «конец оплаты» сообщит его закрытие
        // (closeKgsChooser), иначе попап скидки вылез бы поверх окна.
        // Закрытое окно своё состояние уже сбросило — чужое не трогаем.
        if (!leaving && !dismissed()) setKgsBusy(null);
      } else {
        onPurchaseEnd?.();
      }
      if (retryPlain) {
        // Последним в finally: кнопки уже отпущены, новая оплата займёт их
        // заново. Окно выбора убираем без «конца оплаты» — его сообщит она.
        kgsSession.current += 1;
        setKgsPick(null);
        setKgsBusy(null);
        setKgsError("");
        setKgsHeld(null);
        void startCardPurchase(pkg, "KGS");
      }
    }
  };

  /**
   * Бейдж и выделение приходят из данных (TokenPackage.badge / .featured,
   * правятся в админке). Текущий состав: Старт / Про (выделен) / Премиум /
   * Максимум. Если ни у кого нет featured (старые данные) — фолбэк на
   * совпадение по имени ("про"/"pro"), чтобы выделение не пропало.
   */
  // Выделенный пакет приходит из данных (TokenPackage.featured, правится в
  // админке). Фолбэк на совпадение по имени («про»/«pro») — для старых данных.
  const anyFeatured = packages.some((p) => p.featured);
  const featuredFallbackIndex = (() => {
    if (anyFeatured) return -1;
    const byName = packages.findIndex((p) => /про|pro/i.test(p.name || ""));
    if (byName !== -1) return byName;
    return packages.length >= 3 ? 1 : -1;
  })();

  // Скидку «при уходе» бэкенд применяет только к оплате в сомах (FreedomPay):
  // крипта и ЮKassa уходят своим путём раньше и списывают полную цену.
  // Показывать зачёркнутую цену в рублях или долларах — значит обещать сумму,
  // которую не спишут (находка аудита).
  const shownDiscount = currency === "KGS" ? discountPercent : null;

  // Подпись валюты у цены. Раньше её склеивали прямо в разметке, но с
  // долларом вариантов стало три, и в двух витринах они разошлись бы.
  const priceText = (priceKgs: number): string => {
    if (format) return format(priceKgs, t("topup.som", { defaultValue: "сом" }));
    const shown = convert(priceKgs).toLocaleString();
    return `${shown} ${currency === "RUB" ? "₽" : t("topup.som", { defaultValue: "сом" })}`;
  };

  const tagline = (p: Pkg, idx: number): string => {
    if (p.description && p.description.trim()) return p.description;
    const defaults = [
      t("packages.tagline_start", { defaultValue: "Для студентов и быстрых задач" }),
      t("packages.tagline_pro", { defaultValue: "Для копирайтеров, SMM, маркетологов, юристов" }),
      t("packages.tagline_business", { defaultValue: "Программисты, команда, тяжёлые PDF/Excel" }),
    ];
    return defaults[idx] || "";
  };

  return (
    <div className="w-full px-4 sm:px-8 lg:px-16 xl:px-24 2xl:px-40 py-10">
      {/* Вернуть человека туда, откуда он ушёл. Без этого единственным
          способом продолжить было начать оплату заново — и один человек в
          разборе воронки нажал «Пополнить» десять раз подряд. */}
      {pending && !pendingHidden && pending.kind === "crypto" && (
        <CryptoPendingBanner
          packageName={pending.package}
          coin={pending.coin}
          network={pending.network}
          payAmount={pending.amount_remaining || pending.pay_amount}
          expiresAt={pending.expires_at}
          onOpen={() => setCheckout({ pkg: null, resumeOrderId: pending.order_id })}
          onDismiss={() => setPendingHidden(true)}
        />
      )}

      {pending && !pendingHidden && pending.kind !== "crypto" && (
        <div className="mx-auto mb-6 flex max-w-2xl flex-col gap-3 rounded-2xl border border-accent/50 bg-accent/5 p-4 sm:flex-row sm:items-center">
          <div className="flex-1">
            <p className="text-sm font-semibold text-foreground">
              {t("packages.pending_title", { defaultValue: "У вас есть незавершённая оплата" })}
            </p>
            <p className="mt-0.5 text-sm text-muted">
              {pending.package} — {Number(pending.amount).toLocaleString("ru-RU")}{" "}
              {pending.currency === "KGS" ? t("topup.som", { defaultValue: "сом" }) : pending.currency}
            </p>
          </div>
          <a
            href={pending.redirect_url}
            className="inline-flex shrink-0 items-center justify-center rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong"
          >
            {t("packages.pending_continue", { defaultValue: "Продолжить оплату" })}
          </a>
          <button
            type="button"
            onClick={() => setPendingHidden(true)}
            className="shrink-0 text-sm text-muted transition-colors hover:text-foreground cursor-pointer"
          >
            {t("packages.pending_dismiss", { defaultValue: "Скрыть" })}
          </button>
        </div>
      )}

      {loading && (
        <div className="py-10 text-center text-muted">{t("common.loading", { defaultValue: "Загрузка..." })}</div>
      )}

      {error && (
        <div className="mx-auto mb-6 max-w-md rounded-lg border border-rose-500/40 bg-rose-500/10 text-status-fail text-sm px-3 py-2 text-center">
          {error}
        </div>
      )}

      {!loading && packages.length === 0 && !error && (
        <div className="py-10 text-center text-muted">
          {t("topup.empty", { defaultValue: "Пакеты пока недоступны" })}
        </div>
      )}

      {checkout && (
        <CryptoCheckoutModal
          open
          pkg={checkout.pkg}
          priceKgs={checkout.pkg?.price}
          priceLabel={checkout.pkg ? priceText(checkout.pkg.price) : undefined}
          currencies={crypto.currencies}
          resumeOrderId={checkout.resumeOrderId || null}
          deviceKey={deviceKey}
          returnTo={returnTo}
          onPaid={() => setPending(null)}
          onCardPurchase={
            checkout.pkg
              ? (payCurrency) => {
                  const pkg = checkout.pkg as Pkg;
                  setCheckout(null);
                  // «Карта · сом» из окна крипты — та же оплата в сомах:
                  // ведём через тот же выбор способа.
                  if (payCurrency === "KGS" && kgsMethods.length > 0) {
                    openKgsChooser(pkg);
                    return;
                  }
                  void startCardPurchase(pkg, payCurrency);
                }
              : undefined
          }
          onClose={() => {
            setCheckout(null);
            onPurchaseEnd?.();
          }}
        />
      )}

      {/* Одновременно с окном крипты не открывается: оба живут по одному
          (две модалки ломают друг другу Escape и блокировку прокрутки). */}
      {kgsPick && !checkout && (
        <KgsMethodModal
          open
          methods={kgsMethods}
          packageName={kgsPick.name}
          priceLabel={kgsPriceLabel(kgsPick)}
          busyKey={kgsBusy}
          error={kgsError}
          held={kgsHeld}
          onPick={onKgsPick}
          onPayFull={() => {
            if (kgsHeld) void startCardPurchase(kgsPick, "KGS", kgsHeld.method, true);
          }}
          onClose={closeKgsChooser}
        />
      )}

      {!loading && packages.length > 0 && (
        <div className="grid gap-5 w-full justify-center items-stretch [grid-template-columns:repeat(auto-fit,minmax(260px,340px))]">
          {packages.map((p, idx) => {
            const featured = Boolean(p.featured) || idx === featuredFallbackIndex;
            const v = valueById[String(p.id)] || {};
            const valueRows: { key: string; node: string }[] = [];
            if (v.text) {
              valueRows.push({
                key: "text",
                node: t("packages.value_text", {
                  count: v.text.count,
                  defaultValue: "💬 До {{count}} обычных запросов",
                }),
              });
            }
            if (v.image) {
              valueRows.push({
                key: "image",
                node: t("packages.value_image", {
                  count: v.image.count,
                  defaultValue: "🎨 До {{count}} изображений",
                }),
              });
            }
            if (v.video) {
              valueRows.push({
                key: "video",
                node: t("packages.value_video", {
                  count: v.video.count,
                  defaultValue: "🎬 До {{count}} видео",
                }),
              });
            }
            if (v.document) {
              valueRows.push({
                key: "document",
                node: t("packages.value_document", {
                  count: v.document.count,
                  defaultValue: "📄 До {{count}} страниц перевода",
                }),
              });
            }
            const custom = valueOverride ? valueOverride(p) : null;
            return (
              <div
                key={p.id}
                className={`relative rounded-2xl bg-surface transition-colors p-6 sm:p-8 flex flex-col gap-5 ${
                  featured
                    ? "border-2 border-accent shadow-lg shadow-accent/10 sm:scale-[1.03]"
                    : "border border-border hover:border-accent/60"
                }`}
              >
                {p.badge && p.badge.trim() && (
                  <span
                    className={`absolute -top-3 left-1/2 -translate-x-1/2 inline-flex items-center gap-1 rounded-full text-xs font-bold tracking-wide px-3 py-1 shadow whitespace-nowrap ${
                      featured
                        ? "bg-accent text-on-accent"
                        : "bg-surface-2 border border-border text-foreground"
                    }`}
                  >
                    {p.badge}
                  </span>
                )}

                <div className="text-center text-foreground text-lg font-semibold">{p.name}</div>

                <div className="text-center">
                  {shownDiscount ? (
                    <>
                      <span className="text-base text-muted line-through mr-2">
                        {priceText(p.price)}
                      </span>
                      <span className="text-2xl font-bold text-accent">
                        {priceText(Math.round(p.price * (1 - shownDiscount / 100) * 100) / 100)}
                      </span>
                    </>
                  ) : (
                    <span className="text-2xl font-bold text-foreground">{priceText(p.price)}</span>
                  )}
                </div>

                {/* Сырой счётчик кредитов — вторично, мелким текстом (п.8 ТЗ:
                    продаём возможности, а не кредиты). Денежная логика не
                    затронута — это чисто отображение существующих полей. */}
                <div className="flex flex-col items-center gap-0.5">
                  <div className="flex items-baseline gap-1.5 text-xs text-muted">
                    <span>{p.tokens.toLocaleString()}</span>
                    <span>{t("topup.credits", { defaultValue: "кредитов" })}</span>
                  </div>
                  {!!p.bonus_tokens && p.bonus_tokens > 0 && (
                    <div className="inline-flex items-center gap-1 text-xs text-accent">
                      <FiGift /> +{p.bonus_tokens.toLocaleString()} {t("topup.bonus", { defaultValue: "бонус" })}
                    </div>
                  )}
                </div>

                {custom ? (
                  <div className="rounded-xl bg-surface-2 border border-border px-3.5 py-3 flex flex-col gap-1.5">
                    <div className="text-xs font-semibold text-muted uppercase tracking-wide">{custom.title}</div>
                    <ul className="flex flex-col gap-1 text-sm text-foreground">
                      {custom.rows.map((r) => (
                        <li key={r}>{r}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {!custom && valueRows.length > 0 && (
                  <div className="rounded-xl bg-surface-2 border border-border px-3.5 py-3 flex flex-col gap-1.5">
                    <div className="text-xs font-semibold text-muted uppercase tracking-wide">
                      {t("packages.value_title", { defaultValue: "Примерно хватит на" })}
                    </div>
                    <ul className="flex flex-col gap-1 text-sm text-foreground">
                      {valueRows.map((r) => (
                        <li key={r.key}>{r.node}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {tagline(p, idx) && (
                  <p className="text-center text-sm text-muted min-h-[2.5rem]">{tagline(p, idx)}</p>
                )}

                <button
                  type="button"
                  onClick={() => onBuy(p)}
                  disabled={buyingId != null}
                  className={`mt-auto inline-flex items-center justify-center gap-2 rounded-xl font-semibold text-sm py-3 transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed ${
                    featured
                      ? "bg-accent text-on-accent hover:bg-accent-strong"
                      : "bg-accent/90 text-on-accent hover:bg-accent-strong"
                  }`}
                >
                  <FiZap />
                  {!authed
                    ? t("packages.login_to_topup", { defaultValue: "Войдите, чтобы пополнить" })
                    : buyingId === p.id
                    ? t("common.processing", { defaultValue: "Обработка..." })
                    : t("packages.topup", { defaultValue: "Пополнить" })}
                </button>

              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
