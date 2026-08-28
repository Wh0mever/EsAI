// next/src/hooks/usePackagesValue.ts
"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { apiLang } from "@/lib/apiLang";
import type { PkgWithValue } from "@/types/pricing";

export type UsePackagesValueResult = {
  data: PkgWithValue[];
  loading: boolean;
  error: boolean;
};

/**
 * usePackagesValue — общий хук для публичного (без авторизации) эндпоинта
 * GET /api/plans/packages/value/ (core/plans/views.py TokenPackageValueListView,
 * core/plans/credit_value.py compute_all_packages_value).
 *
 * Используется WhatsEnoughCalculator, HomePricingPreview и TopUpModal —
 * раньше каждый компонент независимо описывал тип ответа и делал свой
 * fetch с почти идентичной обработкой skeleton/ошибки; вынесено сюда без
 * изменения поведения (1:1).
 *
 * @param enabled — по умолчанию `true` (старое поведение: один fetch сразу
 * при монтировании). Компоненты, смонтированные всегда независимо от
 * видимости (напр. TopUpModal — рендерится в дереве чата постоянно, `Modal`
 * внутри просто возвращает `null` при `open=false`), должны передавать
 * `enabled={open}`, чтобы не бить публичный эндпоинт на каждой загрузке
 * чата. Fetch запускается один раз, как только `enabled` впервые становится
 * `true` (ref-флаг), и не повторяется при последующих переключениях —
 * повторные рендеры/переоткрытия используют уже загруженные данные.
 */
export function usePackagesValue(enabled: boolean = true): UsePackagesValueResult {
  const [data, setData] = useState<PkgWithValue[]>([]);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState(false);
  // Имена и бейджи пакетов переводятся в базе, поэтому «уже загружено»
  // считается для конкретного языка: после переключения нужны новые данные.
  const { i18n } = useTranslation();
  const lang = apiLang(i18n.language);
  const startedRef = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled || startedRef.current === lang) return;
    startedRef.current = lang;
    let cancelled = false;
    setLoading(true);
    setError(false);
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
          const sorted = [...list].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
          setData(sorted);
        } else {
          setError(true);
        }
      } catch {
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled, lang]);

  return { data, loading, error };
}
