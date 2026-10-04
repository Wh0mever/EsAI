"use client";

import { Suspense, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { MODE, labelFrom } from "./_shared/labels";
import { CreatorsRoleProvider, useCreatorsRole } from "./_shared/role";
import { ErrorBox, Skeleton } from "./_shared/ui";

const BASE = "/admin-new/creators";

/** Вкладки раздела — порядок ТЗ п.29, плюс «Уровни», «Журнал» и «Настройки». */
const TABS: { href: string; label: string }[] = [
  { href: BASE, label: "Заявки" },
  { href: `${BASE}/list`, label: "Все Creators" },
  { href: `${BASE}/publications`, label: "Публикации" },
  { href: `${BASE}/referrals`, label: "Рефералы" },
  { href: `${BASE}/commissions`, label: "Комиссии" },
  { href: `${BASE}/withdrawals`, label: "Выплаты" },
  { href: `${BASE}/credits`, label: "Creator Credits" },
  { href: `${BASE}/levels`, label: "Уровни" },
  { href: `${BASE}/log`, label: "Журнал" },
  { href: `${BASE}/settings`, label: "Настройки" },
];

function isActive(pathname: string, href: string): boolean {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (href === BASE) return path === BASE;
  // Профиль креатора (/creators/12) — часть вкладки «Все Creators».
  if (href === `${BASE}/list`) return path === href || /^\/admin-new\/creators\/\d+$/.test(path);
  return path === href || path.startsWith(`${href}/`);
}

/** Строка состояния программы. Настройки видит только главный администратор. */
function ProgramLine() {
  const { role, settings, probeError } = useCreatorsRole();
  if (role === "checking") return <p className="mt-1 text-sm text-muted-2">Проверяю права…</p>;
  if (probeError) {
    return (
      <ErrorBox
        className="mt-2"
        error="Не удалось определить ваши права — денежные действия выключены. Обновите страницу."
      />
    );
  }
  if (!settings) {
    return (
      <p className="mt-1 text-sm text-muted">
        Вы вошли как сотрудник: можно проверять заявки и публикации. Деньги, уровни, промокоды и настройки — только
        главный администратор.
      </p>
    );
  }
  return (
    <p className="mt-1 text-sm text-muted">
      Режим: <span className="text-foreground">{labelFrom(MODE, settings.mode).toLowerCase()}</span> ({settings.mode}) ·
      Выводы: <span className="text-foreground">{settings.payouts_enabled ? "принимаются" : "не принимаются"}</span> ·
      Холд: <span className="text-foreground">{settings.hold_days} дн.</span>
    </p>
  );
}

export default function AdminCreatorsLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname() || BASE;

  return (
    <CreatorsRoleProvider>
      <div className="space-y-5">
        <div>
          <h1 className="text-2xl font-semibold">EsAI Creators</h1>
          <ProgramLine />
        </div>

        <nav className="-mx-4 flex gap-1 overflow-x-auto border-b border-border px-4 pb-2 md:mx-0 md:px-0">
          {TABS.map((tab) => (
            <Link
              key={tab.href}
              href={tab.href}
              className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-lg px-3 py-1.5 text-sm transition-colors ${
                isActive(pathname, tab.href)
                  ? "bg-accent-soft font-medium text-accent"
                  : "text-muted hover:bg-surface-2 hover:text-foreground"
              }`}
            >
              {tab.label}
            </Link>
          ))}
        </nav>

        {/* Вкладки читают фильтр из адресной строки (?creator=) — useSearchParams нужна граница Suspense. */}
        <Suspense fallback={<Skeleton />}>{children}</Suspense>
      </div>
    </CreatorsRoleProvider>
  );
}
