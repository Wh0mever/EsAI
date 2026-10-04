"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { adminSettings } from "@/lib/creators/adminApi";
import type { AdminSettings } from "@/lib/creators/adminTypes";
import type { CrError } from "@/lib/creators/types";

/**
 * Кто смотрит раздел: главный администратор или обычный сотрудник.
 *
 * Поля is_superuser API не отдаёт, поэтому роль узнаём пробой: настройки
 * программы (GET manage/creators/settings/) открыты только главному
 * администратору, сотруднику сервер отвечает 403 superuser_required.
 * Это подсказка для интерфейса (какие кнопки выключить); решает всё равно сервер.
 */
export type Role = "checking" | "superuser" | "staff";

export type RoleValue = {
  role: Role;
  isSuperuser: boolean;
  /** Настройки программы — только у главного администратора. */
  settings: AdminSettings | null;
  setSettings: (settings: AdminSettings) => void;
  /** Проба не удалась не из-за роли (сеть, 5xx): кнопки выключены, причину показываем. */
  probeError: CrError | null;
};

const RoleContext = createContext<RoleValue>({
  role: "checking",
  isSuperuser: false,
  settings: null,
  setSettings: () => {},
  probeError: null,
});

export type RoleProbe = { role: "superuser" | "staff"; settings: AdminSettings | null; error: CrError | null };

/** Проба роли. Любой отказ, кроме успеха, оставляет денежные кнопки выключенными. */
export async function probeRole(): Promise<RoleProbe> {
  const res = await adminSettings();
  if (res.ok) return { role: "superuser", settings: res.data, error: null };
  return {
    role: "staff",
    settings: null,
    error: res.error.code === "superuser_required" ? null : res.error,
  };
}

export function CreatorsRoleProvider({ children }: { children: ReactNode }) {
  const [probe, setProbe] = useState<RoleProbe | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const result = await probeRole();
      if (alive) setProbe(result);
    })();
    return () => {
      alive = false;
    };
  }, []);

  const value = useMemo<RoleValue>(
    () => ({
      role: probe ? probe.role : "checking",
      isSuperuser: probe?.role === "superuser",
      settings: probe?.settings ?? null,
      setSettings: (settings) =>
        setProbe((prev) => (prev && prev.role === "superuser" ? { ...prev, settings } : prev)),
      probeError: probe?.error ?? null,
    }),
    [probe],
  );

  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>;
}

export function useCreatorsRole(): RoleValue {
  return useContext(RoleContext);
}
