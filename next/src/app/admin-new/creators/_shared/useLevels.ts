"use client";

import { useEffect, useState } from "react";
import { adminLevels } from "@/lib/creators/adminApi";
import type { AdminLevel } from "@/lib/creators/adminTypes";
import type { CrError } from "@/lib/creators/types";

/** Уровни программы для списков выбора. null — ещё загружаются. */
export function useLevels(): { levels: AdminLevel[] | null; error: CrError | null } {
  const [state, setState] = useState<{ levels: AdminLevel[] | null; error: CrError | null }>({
    levels: null,
    error: null,
  });

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await adminLevels();
      if (!alive) return;
      setState(res.ok ? { levels: res.data.results || [], error: null } : { levels: [], error: res.error });
    })();
    return () => {
      alive = false;
    };
  }, []);

  return state;
}

/** Базовый уровень: только его может назначить обычный сотрудник (levels.BASE_LEVEL_KEY на сервере). */
export const BASE_LEVEL_KEY = "creator";
