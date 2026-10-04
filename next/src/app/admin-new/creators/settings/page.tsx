"use client";

import { useState } from "react";
import { adminPatchSettings } from "@/lib/creators/adminApi";
import type { AdminSettings } from "@/lib/creators/adminTypes";
import type { CrError, CrMode } from "@/lib/creators/types";
import { MODE } from "../_shared/labels";
import { useCreatorsRole } from "../_shared/role";
import { BTN_PRIMARY, CARD, ErrorBox, INPUT, OkBox, PageTitle, Skeleton } from "../_shared/ui";

const MODES: { key: CrMode; hint: string }[] = [
  { key: "off", hint: "Страница программы и кабинет закрыты для всех, комиссии не начисляются." },
  { key: "staff", hint: "Программу видят и могут подавать заявки только сотрудники — для обкатки." },
  { key: "on", hint: "Программа открыта всем пользователям." },
];

/** Настройки программы: режим, приём заявок на вывод, срок холда. Только главный администратор. */
export default function AdminCreatorsSettingsPage() {
  const { role, settings, setSettings, probeError } = useCreatorsRole();

  return (
    <div className="space-y-4">
      <PageTitle title="Настройки" hint="Действуют сразу, без выкладки. Каждое изменение пишется в журнал." />

      {role === "checking" ? (
        <Skeleton className="h-64" />
      ) : probeError ? (
        <ErrorBox error={probeError} />
      ) : !settings ? (
        <div className={`${CARD} text-sm text-muted`}>Доступно только главному администратору.</div>
      ) : (
        <SettingsForm initial={settings} onSaved={setSettings} />
      )}
    </div>
  );
}

function SettingsForm({ initial, onSaved }: { initial: AdminSettings; onSaved: (settings: AdminSettings) => void }) {
  // Что сейчас на сервере: от него считаем «что изменилось» и после сохранения.
  const [current, setCurrent] = useState(initial);
  const [mode, setMode] = useState<CrMode>(initial.mode);
  const [payouts, setPayouts] = useState(initial.payouts_enabled);
  const [holdDays, setHoldDays] = useState(String(initial.hold_days));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<CrError | string | null>(null);
  const [saved, setSaved] = useState(false);

  const save = async () => {
    const days = holdDays.trim();
    if (!/^\d{1,2}$/.test(days) || Number(days) > 90) return setError("Холд: целое число дней от 0 до 90");

    // Шлём только изменённые ключи: в журнал попадает ровно правка.
    const changes: Partial<AdminSettings> = {};
    if (mode !== current.mode) changes.mode = mode;
    if (payouts !== current.payouts_enabled) changes.payouts_enabled = payouts;
    if (Number(days) !== current.hold_days) changes.hold_days = Number(days);
    if (Object.keys(changes).length === 0) return setError("Нечего сохранять: значения те же");

    if (
      changes.mode &&
      !confirm(`Сменить режим программы: «${MODE[current.mode]}» → «${MODE[changes.mode]}»?\nЭто сразу меняет, кто видит программу.`)
    ) {
      return;
    }

    setBusy(true);
    setError(null);
    setSaved(false);
    const res = await adminPatchSettings(changes);
    setBusy(false);
    if (!res.ok) return setError(res.error);
    setCurrent(res.data);
    setMode(res.data.mode);
    setPayouts(res.data.payouts_enabled);
    setHoldDays(String(res.data.hold_days));
    setSaved(true);
    onSaved(res.data);
  };

  return (
    <form
      className={`${CARD} max-w-2xl space-y-6`}
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
    >
      <fieldset className="space-y-2">
        <legend className="text-sm font-semibold">Режим программы</legend>
        {MODES.map((item) => (
          <label
            key={item.key}
            className={`flex cursor-pointer items-start gap-3 rounded-xl border px-3 py-2.5 transition-colors ${
              mode === item.key ? "border-accent bg-accent/10" : "border-border hover:bg-surface-2"
            }`}
          >
            <input
              type="radio"
              name="creators-mode"
              checked={mode === item.key}
              onChange={() => setMode(item.key)}
              className="mt-1 accent-accent"
            />
            <span className="min-w-0 text-sm">
              <span className="font-medium">{MODE[item.key]}</span>{" "}
              <span className="font-mono text-xs text-muted-2">({item.key})</span>
              <span className="block text-xs text-muted">{item.hint}</span>
            </span>
          </label>
        ))}
        <p className="text-xs text-status-wait">
          При режиме «on» включите NEXT_PUBLIC_CREATORS_NAV=1 в сборке сайта — иначе ссылки на программу в меню не будет.
        </p>
      </fieldset>

      <label className="flex cursor-pointer items-start gap-3">
        <input
          type="checkbox"
          checked={payouts}
          onChange={(e) => setPayouts(e.target.checked)}
          className="mt-1 accent-accent"
        />
        <span className="text-sm">
          <span className="font-semibold">Принимать заявки на вывод</span>
          <span className="block text-xs text-muted">
            Выключено — креаторы не могут создать новую заявку. Уже поданные заявки остаются в работе.
          </span>
        </span>
      </label>

      <label className="block text-sm">
        <span className="font-semibold">Холд, дней</span>
        <span className="block text-xs text-muted">
          Через сколько дней после начисления комиссия становится доступной к выводу. От 0 до 90.
        </span>
        <input
          value={holdDays}
          onChange={(e) => setHoldDays(e.target.value)}
          inputMode="numeric"
          className={`${INPUT} mt-1.5 w-28`}
        />
      </label>

      <ErrorBox error={error} />
      {saved && <OkBox>Настройки сохранены.</OkBox>}

      <button type="submit" disabled={busy} className={BTN_PRIMARY}>
        {busy ? "Сохраняю…" : "Сохранить"}
      </button>
    </form>
  );
}
