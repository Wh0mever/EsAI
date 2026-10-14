"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import EsaiLogo from "@/components/brand/EsaiLogo";
import { fetchData } from "@/tools/fetchData";
import Cookies from "js-cookie";
import {
  FiHome,
  FiCpu,
  FiPackage,
  FiUsers,
  FiCreditCard,
  FiFileText,
  FiTag,
  FiSettings,
  FiShield,
  FiArrowLeft,
  FiLock,
  FiEye,
  FiEyeOff,
  FiKey,
  FiFilter,
  FiFilm,
  FiActivity,
  FiAward,
  FiVideo,
  FiLayers,
} from "react-icons/fi";

const NAV = [
  { href: "/admin-new", label: "Дашборд", icon: FiHome },
  { href: "/admin-new/models", label: "Модели", icon: FiCpu },
  { href: "/admin-new/packages", label: "Пакеты", icon: FiPackage },
  { href: "/admin-new/users", label: "Пользователи", icon: FiUsers },
  { href: "/admin-new/payments", label: "Платежи", icon: FiCreditCard },
  { href: "/admin-new/funnel", label: "Воронка", icon: FiFilter },
  { href: "/admin-new/studio-works", label: "Работы", icon: FiFilm },
  { href: "/admin-new/studio-scenes", label: "Сцены мультстудии", icon: FiLayers },
  { href: "/admin-new/vstudio-showcase", label: "Витрина", icon: FiVideo },
  { href: "/admin-new/generations", label: "Генерации", icon: FiActivity },
  { href: "/admin-new/blocks", label: "Блокировки", icon: FiShield },
  { href: "/admin-new/blog", label: "Блог", icon: FiFileText },
  { href: "/admin-new/promo", label: "Промокоды", icon: FiTag },
  { href: "/admin-new/creators", label: "Creators", icon: FiAward },
  { href: "/admin-new/openrouter", label: "OpenRouter", icon: FiKey },
  { href: "/admin-new/settings", label: "Настройки", icon: FiSettings },
];

type Gate = "checking" | "ok" | "denied";

/**
 * Клиентская оболочка админки (проверка доступа, навигация). Вынесена из
 * layout.tsx, чтобы layout остался серверным и мог отдать metadata с noindex:
 * у клиентского layout метаданных нет, и /admin-new наследовал canonical и
 * индексацию от корня.
 */
export default function AdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [gate, setGate] = useState<Gate>("checking");

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData("manage/config/", "GET", null, true);
      if (!alive) return;
      // Fail CLOSED: только явный 2xx открывает админку. Сетевые ошибки
      // (fetchData отдаёт status:0), временные 5xx и любой другой не-2xx
      // статус должны блокировать доступ, а не открывать его — иначе сбой
      // бэкенда во время проверки временно снимает авторизацию для всех.
      if (res.status >= 200 && res.status < 300) setGate("ok");
      else setGate("denied");
    })();
    return () => {
      alive = false;
    };
  }, []);

  const isActive = (href: string) =>
    href === "/admin-new" ? pathname === "/admin-new" : pathname.startsWith(href);

  return (
    <div data-theme="dark" className="bg-background text-foreground min-h-[100dvh]">
      {/* Верхняя панель */}
      <header className="sticky top-0 z-20 border-b border-border bg-background/90 backdrop-blur pt-[env(safe-area-inset-top,0px)]">
        <div className="flex h-14 items-center gap-3 px-4 md:px-6">
          <Link href="/admin-new" className="flex items-center gap-2.5">
            <EsaiLogo className="h-7 w-auto" />
            <span className="hidden text-sm font-semibold text-muted sm:inline">
              Админка EsAI
            </span>
          </Link>
          <Link
            href="/"
            className="ml-auto inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
          >
            <FiArrowLeft className="h-4 w-4" />
            На сайт
          </Link>
        </div>

        {/* Мобильные вкладки */}
        <nav className="flex gap-1 overflow-x-auto border-t border-border px-2 py-1.5 md:hidden">
          {NAV.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm transition-colors ${
                  active
                    ? "bg-accent-soft font-medium text-accent"
                    : "text-muted hover:bg-surface-2 hover:text-foreground"
                }`}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </header>

      <div className="flex">
        {/* Сайдбар */}
        <aside className="sticky top-14 hidden h-[calc(100dvh-3.5rem)] w-60 shrink-0 flex-col border-r border-border p-3 md:flex">
          <nav className="flex flex-col gap-1">
            {NAV.map((item) => {
              const Icon = item.icon;
              const active = isActive(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm transition-colors ${
                    active
                      ? "bg-accent-soft font-medium text-accent"
                      : "text-muted hover:bg-surface-2 hover:text-foreground"
                  }`}
                >
                  <Icon className="h-[18px] w-[18px]" />
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <p className="mt-auto px-3 pb-2 text-xs text-muted-2">
            Панель управления · только для персонала
          </p>
        </aside>

        {/* Контент */}
        <main className="min-w-0 flex-1 p-4 md:p-8">
          {gate === "checking" && (
            <div className="space-y-4">
              <div className="h-8 w-56 animate-pulse rounded-lg bg-surface-2" />
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <div key={i} className="h-28 animate-pulse rounded-2xl bg-surface-2" />
                ))}
              </div>
            </div>
          )}

          {gate === "denied" && <AdminLoginCard onSuccess={() => setGate("ok")} />}

          {gate === "ok" && children}
        </main>
      </div>
    </div>
  );
}

/**
 * Форма входа в админку: email + пароль (с «глазком»). Бьёт в /api/manage/login/
 * (только staff), кладёт JWT в те же cookies, что и обычный вход, и открывает панель.
 */
function AdminLoginCard({ onSuccess }: { onSuccess: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      // Отказ приходит тем же адресом, только с detail вместо токенов.
      const res = await fetchData<{ access?: string; refresh?: string; detail?: string }>(
        "manage/login/", "POST", { email: email.trim(), password }, false
      );
      const data = res.data;
      if (res.ok && data?.access) {
        Cookies.set("access", data.access, { expires: 7 });
        if (data.refresh) Cookies.set("refresh", data.refresh, { expires: 15 });
        onSuccess();
      } else {
        setErr(data?.detail || "Неверный email или пароль.");
      }
    } catch {
      setErr("Не удалось выполнить вход. Попробуйте ещё раз.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-[60dvh] items-center justify-center">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-border bg-surface p-8">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-accent-soft">
          <FiLock className="h-5 w-5 text-accent" />
        </div>
        <h1 className="text-center text-lg font-semibold">Вход в админку</h1>
        <p className="mt-1 text-center text-sm text-muted">Только для администраторов EsAI</p>

        <label className="mt-6 block text-sm text-muted">Email</label>
        <input
          type="email"
          required
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="admin@example.com"
          className="mt-1.5 w-full rounded-lg border border-border bg-surface-2 px-3 py-2.5 text-sm text-foreground outline-none focus:border-accent"
        />

        <label className="mt-4 block text-sm text-muted">Пароль</label>
        <div className="relative mt-1.5">
          <input
            type={showPw ? "text" : "password"}
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2.5 pr-11 text-sm text-foreground outline-none focus:border-accent"
          />
          {/* «Глазок»: показать/скрыть пароль (просьба клиента) */}
          <button
            type="button"
            onClick={() => setShowPw((v) => !v)}
            title={showPw ? "Скрыть пароль" : "Показать пароль"}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-muted hover:text-foreground cursor-pointer"
          >
            {showPw ? <FiEyeOff className="h-4 w-4" /> : <FiEye className="h-4 w-4" />}
          </button>
        </div>

        {err && <p className="mt-3 text-sm text-rose-400">{err}</p>}

        <button
          type="submit"
          disabled={busy}
          className="mt-6 w-full rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-60 cursor-pointer"
        >
          {busy ? "Входим..." : "Войти"}
        </button>
      </form>
    </div>
  );
}
