"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchData } from "@/tools/fetchData";
import {
  FiAlertTriangle,
  FiChevronDown,
  FiGlobe,
  FiMail,
  FiPlus,
  FiRefreshCw,
  FiShield,
  FiSlash,
  FiSmartphone,
  FiTrash2,
  FiWifi,
  FiX,
} from "react-icons/fi";

/**
 * Блокировки — раздел панели /admin-new.
 *
 * Задача: массовые регистрации с одноразовой почты. Панель показывает, откуда
 * заведено больше одного аккаунта (домены, устройства, IP), даёт заблокировать
 * находку в один клик и сразу говорит, сколько живых аккаунтов при этом
 * закрылось и каких именно.
 *
 * Блокировка обратима: снятие правила возвращает доступ всем, кого оно
 * отключило, и любой аккаунт можно вернуть по отдельности.
 */

type Account = {
  id: number;
  email: string;
  name: string;
  is_active: boolean;
  balance: number;
  date_joined: string | null;
};

type Rule = {
  id: number;
  kind: "domain" | "ip" | "subnet" | "device";
  kind_label: string;
  value: string;
  block_login: boolean;
  reason: string;
  is_active: boolean;
  hits: number;
  last_hit_at: string | null;
  created_at: string | null;
  accounts_total: number;
  accounts_blocked: number;
  accounts?: Account[];
  just_blocked?: Account[];
};

type Suspect = {
  value: string;
  accounts: number;
  active?: number;
  first_seen?: string;
  last_seen?: string;
};

type Suspects = { domains: Suspect[]; devices: Suspect[]; ips: Suspect[] };

const INPUT =
  "rounded-lg bg-surface-2 border border-border px-3 py-2 text-sm text-foreground focus:border-accent outline-none";

const KINDS = [
  { key: "domain", label: "Домен почты", icon: FiMail, hint: "jmaie.com — поддомены тоже попадут" },
  { key: "device", label: "Устройство (UUID)", icon: FiSmartphone, hint: "закроет ВСЕ аккаунты с этого устройства" },
  { key: "ip", label: "IP-адрес", icon: FiWifi, hint: "203.0.113.41" },
  { key: "subnet", label: "Подсеть", icon: FiGlobe, hint: "203.0.113.0/24" },
] as const;

type KindKey = (typeof KINDS)[number]["key"];

function kindIcon(kind: string) {
  const found = KINDS.find((k) => k.key === kind);
  return found ? found.icon : FiSlash;
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/** «3 аккаунта» / «5 аккаунтов» — иначе в панели везде торчало бы «3 аккаунтов». */
function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return `${n} ${one}`;
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return `${n} ${few}`;
  return `${n} ${many}`;
}

export default function AdminBlocksPage() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [suspects, setSuspects] = useState<Suspects>({ domains: [], devices: [], ips: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [kind, setKind] = useState<KindKey>("domain");
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [blockLogin, setBlockLogin] = useState(true);
  const [deactivate, setDeactivate] = useState(true);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Итог последней блокировки: «заблокировано N аккаунтов» + кого именно.
  const [flash, setFlash] = useState<{ title: string; accounts: Account[] } | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    const [r, s] = await Promise.all([
      fetchData<Rule[]>("manage/blocks/", "GET", null, true),
      fetchData<Suspects>("manage/blocks/suspects/", "GET", null, true),
    ]);
    if (r.ok && Array.isArray(r.data)) setRules(r.data);
    else setError(r.error || "Не удалось загрузить правила");
    if (s.ok && s.data) setSuspects(s.data);
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async (override?: { kind: KindKey; value: string }) => {
    const k = override?.kind ?? kind;
    const v = (override?.value ?? value).trim();
    if (!v) {
      setCreateError("Укажите значение");
      return;
    }
    setCreating(true);
    setCreateError(null);
    const res = await fetchData<Rule>(
      "manage/blocks/",
      "POST",
      { kind: k, value: v, block_login: blockLogin, deactivate, reason },
      true
    );
    setCreating(false);
    if (!res.ok || !res.data) {
      setCreateError((res.data as any)?.detail || res.error || "Не удалось создать правило");
      return;
    }
    const blocked = res.data.just_blocked || [];
    setFlash({
      title: blocked.length
        ? `Заблокировано ${plural(blocked.length, "аккаунт", "аккаунта", "аккаунтов")}`
        : "Правило добавлено. Действующих аккаунтов под него не нашлось",
      accounts: blocked,
    });
    if (!override) {
      setValue("");
      setReason("");
    }
    await load();
  };

  const removeRule = async (rule: Rule) => {
    if (
      !confirm(
        `Снять правило «${rule.value}»?\n\nДоступ вернётся всем аккаунтам, которые оно закрыло (${rule.accounts_blocked}).`
      )
    )
      return;
    setBusy((b) => ({ ...b, [`rule-${rule.id}`]: true }));
    const res = await fetchData<{ restored: number }>(`manage/blocks/${rule.id}/`, "DELETE", null, true);
    setBusy((b) => ({ ...b, [`rule-${rule.id}`]: false }));
    if (res.ok && res.data) {
      setFlash({
        title: res.data.restored
          ? `Правило снято, доступ вернули ${plural(res.data.restored, "аккаунту", "аккаунтам", "аккаунтам")}`
          : "Правило снято",
        accounts: [],
      });
    }
    await load();
  };

  const patchRule = async (rule: Rule, patch: Partial<Rule>) => {
    setBusy((b) => ({ ...b, [`rule-${rule.id}`]: true }));
    await fetchData(`manage/blocks/${rule.id}/`, "PATCH", patch, true);
    setBusy((b) => ({ ...b, [`rule-${rule.id}`]: false }));
    await load();
  };

  const toggleAccounts = async (rule: Rule, action: "block" | "unblock", userId?: number) => {
    const key = userId ? `acc-${userId}` : `all-${rule.id}`;
    setBusy((b) => ({ ...b, [key]: true }));
    const res = await fetchData<{ count: number; accounts: Account[]; rule: Rule }>(
      `manage/blocks/${rule.id}/accounts/`,
      "POST",
      { action, ...(userId ? { user_id: userId } : {}) },
      true
    );
    setBusy((b) => ({ ...b, [key]: false }));
    if (res.ok && res.data && !userId) {
      setFlash({
        title:
          action === "block"
            ? `Заблокировано ${plural(res.data.count, "аккаунт", "аккаунта", "аккаунтов")}`
            : `Доступ вернули ${plural(res.data.count, "аккаунту", "аккаунтам", "аккаунтам")}`,
        accounts: res.data.accounts || [],
      });
    }
    await load();
    if (res.ok && res.data?.rule) {
      setRules((prev) => prev.map((r) => (r.id === rule.id ? { ...r, ...res.data!.rule } : r)));
    }
  };

  const openRule = async (rule: Rule) => {
    if (expanded === rule.id) {
      setExpanded(null);
      return;
    }
    setExpanded(rule.id);
    if (rule.accounts) return;
    const res = await fetchData<Rule>(`manage/blocks/${rule.id}/`, "GET", null, true);
    if (res.ok && res.data) {
      setRules((prev) => prev.map((r) => (r.id === rule.id ? { ...r, ...res.data! } : r)));
    }
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-44 animate-pulse rounded-lg bg-surface-2" />
        <div className="h-44 animate-pulse rounded-2xl bg-surface-2" />
        <div className="h-64 animate-pulse rounded-2xl bg-surface-2" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-border bg-surface p-6 text-sm text-red-400">
        Ошибка загрузки: {error}
      </div>
    );
  }

  const suspectGroups: Array<{ title: string; kind: KindKey; icon: typeof FiMail; rows: Suspect[]; note: string }> = [
    { title: "Домены почты", kind: "domain", icon: FiMail, rows: suspects.domains, note: "Крупные почтовики (gmail, yandex, mail) скрыты — иначе они всегда наверху." },
    { title: "Устройства", kind: "device", icon: FiSmartphone, rows: suspects.devices, note: "Один UUID браузера — несколько аккаунтов. Самый надёжный признак: почту меняют легко, устройство — нет." },
    { title: "IP-адреса", kind: "ip", icon: FiWifi, rows: suspects.ips, note: "От трёх аккаунтов. Осторожно: за одним адресом бывает офис или мобильный оператор." },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Блокировки</h1>
        <p className="mt-1 text-sm text-muted">
          Запрет регистрации и входа по домену почты, устройству, IP или подсети. Блокировка
          обратима: снятие правила возвращает доступ всем, кого оно закрыло.
        </p>
      </div>

      {/* Итог последнего действия — то самое «вы заблокировали N аккаунтов с именами» */}
      {flash && (
        <section className="rounded-2xl border border-accent/50 bg-accent-soft/30 p-5">
          <div className="flex items-start gap-3">
            <FiShield className="mt-0.5 h-5 w-5 shrink-0 text-accent" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-foreground">{flash.title}</p>
              {flash.accounts.length > 0 && (
                <ul className="mt-2 space-y-1 text-xs text-muted">
                  {flash.accounts.slice(0, 30).map((a) => (
                    <li key={a.id} className="truncate">
                      <span className="text-foreground">{a.name}</span>
                      {a.name !== a.email && <span> · {a.email}</span>}
                      <span> · баланс {a.balance}</span>
                    </li>
                  ))}
                  {flash.accounts.length > 30 && (
                    <li>…и ещё {flash.accounts.length - 30}</li>
                  )}
                </ul>
              )}
            </div>
            <button
              type="button"
              onClick={() => setFlash(null)}
              className="shrink-0 rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-foreground"
              title="Скрыть"
            >
              <FiX className="h-4 w-4" />
            </button>
          </div>
        </section>
      )}

      {/* Новое правило */}
      <section className="rounded-2xl border border-border bg-surface p-5">
        <div className="flex items-center gap-2">
          <FiPlus className="h-4 w-4 text-accent" />
          <h2 className="text-base font-semibold">Новая блокировка</h2>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {KINDS.map((k) => {
            const Icon = k.icon;
            const on = kind === k.key;
            return (
              <button
                key={k.key}
                type="button"
                onClick={() => setKind(k.key)}
                aria-pressed={on}
                className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors ${
                  on
                    ? "border-accent bg-accent-soft font-medium text-foreground"
                    : "border-border text-muted hover:border-accent/50 hover:text-foreground"
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {k.label}
              </button>
            );
          })}
        </div>

        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted">Значение</label>
            <input
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={KINDS.find((k) => k.key === kind)?.hint}
              className={`${INPUT} font-mono`}
            />
          </div>
          <div className="flex flex-col gap-1 lg:col-span-2">
            <label className="text-xs text-muted">Причина (для себя)</label>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Одноразовая почта, 10 аккаунтов за 2 часа"
              className={INPUT}
            />
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2">
          <label className="inline-flex items-center gap-2 text-sm text-foreground">
            <input type="checkbox" checked={blockLogin} onChange={(e) => setBlockLogin(e.target.checked)} className="accent-[var(--accent)]" />
            Закрыть и вход существующим
          </label>
          <label className="inline-flex items-center gap-2 text-sm text-foreground">
            <input type="checkbox" checked={deactivate} onChange={(e) => setDeactivate(e.target.checked)} className="accent-[var(--accent)]" />
            Сразу отключить найденные аккаунты
          </label>
        </div>

        {kind === "ip" || kind === "subnet" ? (
          <p className="mt-3 inline-flex items-start gap-2 text-xs text-amber-400">
            <FiAlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            За одним адресом может стоять офис или мобильный оператор. Если не уверены — снимите
            «Закрыть и вход»: регистрация закроется, а живые люди войти смогут.
          </p>
        ) : null}

        {createError && <p className="mt-3 text-sm text-red-400">{createError}</p>}

        <button
          type="button"
          onClick={() => void create()}
          disabled={creating}
          className="mt-4 inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong disabled:opacity-60"
        >
          <FiSlash className="h-4 w-4" />
          {creating ? "Блокирую…" : "Заблокировать"}
        </button>
      </section>

      {/* Подозрительные — «найдём такие, заблокируем массово» */}
      <section className="rounded-2xl border border-border bg-surface p-5">
        <div className="flex items-center gap-2">
          <FiAlertTriangle className="h-4 w-4 text-amber-400" />
          <h2 className="text-base font-semibold">Где заводят по несколько аккаунтов</h2>
        </div>
        <p className="mt-1 text-sm text-muted">
          Отсюда видно фабрики аккаунтов. Нашли одноразовый домен — блокируйте прямо из списка.
        </p>

        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
          {suspectGroups.map((g) => {
            const Icon = g.icon;
            return (
              <div key={g.kind} className="rounded-xl border border-border bg-surface-2 p-4">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <Icon className="h-4 w-4 text-accent" />
                  {g.title}
                </div>
                <p className="mt-1 text-[11px] leading-relaxed text-muted-2">{g.note}</p>
                <div className="mt-3 space-y-1.5">
                  {g.rows.length === 0 && <p className="text-xs text-muted-2">Ничего не нашлось</p>}
                  {g.rows.slice(0, 12).map((row) => {
                    const already = rules.some((r) => r.kind === g.kind && r.value === row.value);
                    return (
                      <div key={row.value} className="flex items-center gap-2">
                        <span className="min-w-0 flex-1 truncate font-mono text-xs text-foreground" title={row.value}>
                          {row.value}
                        </span>
                        <span className="shrink-0 text-xs text-muted">{row.accounts}</span>
                        <button
                          type="button"
                          disabled={already || creating}
                          onClick={() => void create({ kind: g.kind, value: row.value })}
                          className="shrink-0 rounded-md border border-border px-2 py-0.5 text-[11px] text-muted transition-colors hover:border-red-500/60 hover:text-red-400 disabled:opacity-40"
                        >
                          {already ? "в списке" : "блок"}
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Действующие правила */}
      <section className="rounded-2xl border border-border bg-surface p-5">
        <div className="flex items-center gap-2">
          <FiShield className="h-4 w-4 text-accent" />
          <h2 className="text-base font-semibold">Правила ({rules.length})</h2>
        </div>

        {rules.length === 0 && <p className="mt-3 text-sm text-muted">Пока ничего не заблокировано.</p>}

        <div className="mt-4 space-y-2">
          {rules.map((rule) => {
            const Icon = kindIcon(rule.kind);
            const open = expanded === rule.id;
            const ruleBusy = busy[`rule-${rule.id}`];
            return (
              <div key={rule.id} className="rounded-xl border border-border bg-surface-2">
                <div className="flex flex-wrap items-center gap-3 p-3">
                  <button
                    type="button"
                    onClick={() => void openRule(rule)}
                    className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
                  >
                    <Icon className={`h-4 w-4 shrink-0 ${rule.is_active ? "text-red-400" : "text-muted-2"}`} />
                    <span className="min-w-0">
                      <span className="block truncate font-mono text-sm text-foreground">{rule.value}</span>
                      <span className="block truncate text-[11px] text-muted-2">
                        {rule.kind_label} · {plural(rule.accounts_total, "аккаунт", "аккаунта", "аккаунтов")}
                        {rule.accounts_blocked > 0 && ` · закрыто ${rule.accounts_blocked}`}
                        {rule.hits > 0 && ` · сработало ${rule.hits}`}
                        {rule.reason && ` · ${rule.reason}`}
                      </span>
                    </span>
                    <FiChevronDown className={`h-4 w-4 shrink-0 text-muted transition-transform ${open ? "rotate-180" : ""}`} />
                  </button>

                  <label className="inline-flex shrink-0 items-center gap-1.5 text-xs text-muted">
                    <input
                      type="checkbox"
                      checked={rule.block_login}
                      disabled={ruleBusy}
                      onChange={(e) => void patchRule(rule, { block_login: e.target.checked })}
                      className="accent-[var(--accent)]"
                    />
                    вход
                  </label>
                  <label className="inline-flex shrink-0 items-center gap-1.5 text-xs text-muted">
                    <input
                      type="checkbox"
                      checked={rule.is_active}
                      disabled={ruleBusy}
                      onChange={(e) => void patchRule(rule, { is_active: e.target.checked })}
                      className="accent-[var(--accent)]"
                    />
                    вкл
                  </label>
                  <button
                    type="button"
                    onClick={() => void removeRule(rule)}
                    disabled={ruleBusy}
                    title="Снять правило и вернуть доступ"
                    className="shrink-0 rounded-lg p-2 text-muted transition-colors hover:bg-surface hover:text-red-400 disabled:opacity-50"
                  >
                    <FiTrash2 className="h-4 w-4" />
                  </button>
                </div>

                {open && (
                  <div className="border-t border-border p-3">
                    <div className="mb-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => void toggleAccounts(rule, "block")}
                        disabled={busy[`all-${rule.id}`]}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:border-red-500/60 hover:text-red-400 disabled:opacity-50"
                      >
                        <FiSlash className="h-3.5 w-3.5" />
                        Отключить всех
                      </button>
                      <button
                        type="button"
                        onClick={() => void toggleAccounts(rule, "unblock")}
                        disabled={busy[`all-${rule.id}`]}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:border-emerald-500/60 hover:text-emerald-400 disabled:opacity-50"
                      >
                        <FiRefreshCw className="h-3.5 w-3.5" />
                        Вернуть всем доступ
                      </button>
                    </div>

                    {!rule.accounts && <p className="text-xs text-muted-2">Загружаю аккаунты…</p>}
                    {rule.accounts?.length === 0 && (
                      <p className="text-xs text-muted-2">Аккаунтов под это правило пока нет.</p>
                    )}

                    <div className="space-y-1">
                      {rule.accounts?.map((a) => (
                        <div key={a.id} className="flex flex-wrap items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-surface">
                          <span
                            className={`h-1.5 w-1.5 shrink-0 rounded-full ${a.is_active ? "bg-emerald-400" : "bg-red-400"}`}
                            title={a.is_active ? "Активен" : "Отключён"}
                          />
                          <span className="min-w-0 flex-1 truncate text-xs text-foreground">
                            {a.name}
                            {a.name !== a.email && <span className="text-muted-2"> · {a.email}</span>}
                          </span>
                          <span className="shrink-0 text-[11px] text-muted-2">{fmtDate(a.date_joined)}</span>
                          <span className="shrink-0 text-[11px] text-muted-2">{a.balance} кр</span>
                          <button
                            type="button"
                            disabled={busy[`acc-${a.id}`]}
                            onClick={() => void toggleAccounts(rule, a.is_active ? "block" : "unblock", a.id)}
                            className={`shrink-0 rounded-md border px-2 py-0.5 text-[11px] transition-colors disabled:opacity-50 ${
                              a.is_active
                                ? "border-border text-muted hover:border-red-500/60 hover:text-red-400"
                                : "border-border text-muted hover:border-emerald-500/60 hover:text-emerald-400"
                            }`}
                          >
                            {a.is_active ? "отключить" : "вернуть"}
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
