"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import CreatorsUnavailable from "@/components/creators/shared/CreatorsUnavailable";
import ErrorNote from "@/components/creators/shared/ErrorNote";
import { apiLang } from "@/lib/apiLang";
import { getMe, setLang } from "@/lib/creators/api";
import { errorText } from "@/lib/creators/errors";
import type { CodeCreated, CrError, Iso, Me } from "@/lib/creators/types";
import CommissionsTab from "./CommissionsTab";
import CreditsTab from "./CreditsTab";
import FirstScreen from "./FirstScreen";
import OverviewTab from "./OverviewTab";
import PayoutsTab from "./PayoutsTab";
import PublicationsTab from "./PublicationsTab";
import ReferralsTab from "./ReferralsTab";
import { DashboardSkeleton, PAGE } from "./ui";

const TABS = ["overview", "publications", "payouts", "credits", "referrals", "commissions"] as const;
type TabKey = (typeof TABS)[number];

const parseTab = (raw: string | null): TabKey => (TABS.includes(raw as TabKey) ? (raw as TabKey) : "overview");

/**
 * Кабинет креатора /creators/dashboard (ТЗ п.13–16, 19, 22, 25–28, 34, 37–38).
 *
 * Сверху — первый экран (уровень, промокод и ссылка, заработок, результаты,
 * прогресс), под ним разделы по ?tab=. Раздел грузит свои данные при первом
 * открытии и остаётся смонтированным: вернувшись, человек видит тот же список.
 *
 * Заблокированный креатор читает всё, но ничего не создаёт: формы и кнопки,
 * которые пишут, скрыты, язык уведомлений не отправляется.
 */
export default function CreatorDashboard() {
  const { t, i18n, ready } = useTranslation("creators", { useSuspense: false });
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const tab = parseTab(search.get("tab"));

  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<CrError | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [justCreated, setJustCreated] = useState(false);

  // Разделы, которые уже открывали: их данные загружены, заново не монтируем.
  const [opened, setOpened] = useState<readonly TabKey[]>([tab]);
  if (!opened.includes(tab)) setOpened([...opened, tab]);

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await getMe();
      if (!alive) return;
      if (res.ok) {
        setMe(res.data);
        setError(null);
        return;
      }
      setError(res.error);
      // Не креатор (заявки нет, она на рассмотрении или отклонена) — на страницу программы.
      if (res.error.code === "not_creator") router.replace("/creators");
    })();
    return () => {
      alive = false;
    };
  }, [attempt, router]);

  /** Тихо перечитать кабинет после действия: экран не гаснет, цифры обновляются. */
  const reload = () => {
    void (async () => {
      const res = await getMe();
      if (res.ok) {
        setMe(res.data);
        return;
      }
      const code = res.error.code;
      if (code === "disabled") setError(res.error);
      if (code === "not_creator") router.replace("/creators");
    })();
  };

  // Язык уведомлений креатора = язык интерфейса (у пользователя своего поля языка нет).
  const uiLang = apiLang(i18n.language);
  const creatorLang = me?.creator.lang;
  const active = me?.creator.status === "active";
  const langSent = useRef<string | null>(null);
  useEffect(() => {
    if (!active || !creatorLang) return;
    if (creatorLang === uiLang) {
      langSent.current = null;
      return;
    }
    // Один запрос на язык: отказ (сеть, лимит) не повторяем до следующей смены.
    if (langSent.current === uiLang) return;
    langSent.current = uiLang;
    void (async () => {
      const res = await setLang(uiLang);
      if (res.ok) setMe((prev) => (prev ? { ...prev, creator: { ...prev.creator, lang: res.data.lang } } : prev));
    })();
  }, [active, creatorLang, uiLang]);

  const onCodeCreated = (created: CodeCreated) => {
    setJustCreated(true);
    setMe((prev) =>
      prev ? { ...prev, code: created.code, link: created.link, telegram_link: created.telegram_link } : prev,
    );
  };

  const onAddressSaved = (saved: { payout_address: string; payout_address_changed_at: Iso | null }) => {
    setMe((prev) => (prev ? { ...prev, ...saved } : prev));
  };

  const selectTab = (key: TabKey) => {
    const url = key === "overview" ? pathname : `${pathname}?tab=${key}`;
    // Адрес меняем без запроса к серверу: Next встраивает replaceState в свой
    // роутер (useSearchParams обновится сам), раздел открывается сразу и без
    // сети — а введённая сумма вывода и загруженные списки остаются на месте.
    try {
      window.history.replaceState(null, "", url);
    } catch {
      router.replace(url, { scroll: false });
    }
  };

  if (error?.code === "disabled") return <CreatorsUnavailable />;
  // Уходим на /creators — до перехода держим каркас, а не текст ошибки.
  if (error?.code === "not_creator") return <DashboardSkeleton />;
  if (!me && error) {
    return (
      <main className={PAGE}>
        <ErrorNote
          error={error}
          onRetry={() => {
            setError(null);
            setAttempt((n) => n + 1);
          }}
        />
      </main>
    );
  }
  // Пока переводы грузятся, держим каркас — иначе в en/kg мелькнул бы русский текст.
  if (!me || !ready) return <DashboardSkeleton />;

  const blocked = me.creator.status === "blocked";

  const labels: Record<TabKey, string> = {
    overview: t("dash.tabs.overview", { defaultValue: "Обзор" }),
    publications: t("dash.tabs.publications", { defaultValue: "Публикации" }),
    payouts: t("dash.tabs.payouts", { defaultValue: "Выплаты" }),
    credits: "Creator Credits",
    referrals: t("dash.tabs.referrals", { defaultValue: "Рефералы" }),
    commissions: t("dash.tabs.commissions", { defaultValue: "Комиссии" }),
  };

  const panel = (key: TabKey) => {
    switch (key) {
      case "overview":
        return <OverviewTab me={me} />;
      case "publications":
        return <PublicationsTab blocked={blocked} />;
      case "payouts":
        return <PayoutsTab me={me} blocked={blocked} onChanged={reload} onAddressSaved={onAddressSaved} />;
      case "credits":
        return <CreditsTab />;
      case "referrals":
        return <ReferralsTab />;
      case "commissions":
        return <CommissionsTab />;
    }
  };

  return (
    <main className={PAGE}>
      <h1 className="sr-only">{t("entry.cabinet_title", { defaultValue: "Кабинет креатора" })}</h1>

      {blocked && (
        <div
          role="alert"
          className="mb-1.5 rounded-xl border border-status-fail/40 bg-status-fail/10 px-3 py-2 text-sm font-medium text-status-fail"
        >
          {errorText(t, { code: "creator_blocked" })}
        </div>
      )}

      <FirstScreen
        me={me}
        blocked={blocked}
        justCreated={justCreated}
        onCodeCreated={onCodeCreated}
        onReload={reload}
      />

      <div
        role="tablist"
        aria-label={t("dash.tabs.aria", { defaultValue: "Разделы кабинета" })}
        className="-mx-4 mt-3 flex gap-1.5 overflow-x-auto px-4 pb-1 [scrollbar-width:none]"
      >
        {TABS.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            id={`creators-tab-${key}`}
            aria-selected={tab === key}
            aria-controls={`creators-panel-${key}`}
            onClick={() => selectTab(key)}
            className={`shrink-0 cursor-pointer whitespace-nowrap rounded-xl border px-3.5 py-2 text-sm font-medium transition-colors ${
              tab === key
                ? "border-accent bg-accent text-on-accent"
                : "border-border bg-surface text-muted hover:text-foreground"
            }`}
          >
            {labels[key]}
          </button>
        ))}
      </div>

      {TABS.filter((key) => opened.includes(key)).map((key) => (
        <div
          key={key}
          role="tabpanel"
          id={`creators-panel-${key}`}
          aria-labelledby={`creators-tab-${key}`}
          hidden={tab !== key}
          className="mt-3"
        >
          {panel(key)}
        </div>
      ))}
    </main>
  );
}
