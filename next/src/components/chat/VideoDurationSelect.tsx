"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiClock } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";

type VideoParams = {
  model: string;
  durations: number[];
  default_duration: number;
  credits_per_second: number;
};

type Props = {
  /** openrouter_id выбранной видео-модели. */
  model: string;
  value: number | null;
  onChange: (seconds: number) => void;
};

// Кэш на вкладку: параметры модели не меняются в рамках сессии, а селектор
// перемонтируется при каждом переключении модели.
const cache = new Map<string, VideoParams>();

/**
 * VideoDurationSelect — выбор длительности ролика для видео-моделей.
 *
 * До этого длительность была захардкожена в настройках бэкенда (5 секунд), и
 * любая модель выдавала пятисекундный ролик, даже если умеет 30 — из-за чего
 * клиент решил, что Seedance 2.5 «обрывает видео». Теперь список допустимых
 * длительностей приходит с бэкенда (GET ai/video-params/, данные каталога
 * OpenRouter), а рядом сразу показывается цена в кредитах — списание
 * пропорционально секундам, и без цифры перед глазами легко случайно
 * запустить очень дорогую генерацию.
 */
export default function VideoDurationSelect({ model, value, onChange }: Props) {
  const { t } = useTranslation("common");
  const [params, setParams] = useState<VideoParams | null>(cache.get(model) || null);

  useEffect(() => {
    if (!model) return;
    const cached = cache.get(model);
    if (cached) {
      setParams(cached);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchData<VideoParams>(
          `ai/video-params/?model=${encodeURIComponent(model)}`,
          "GET",
          null,
          false
        );
        if (cancelled || !res?.ok || !res.data) return;
        const data = res.data;
        if (!Array.isArray(data.durations) || data.durations.length === 0) return;
        cache.set(model, data);
        setParams(data);
      } catch {
        /* молча: без параметров селектор просто не показываем */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [model]);

  // Значение по умолчанию выставляем один раз, когда параметры приехали.
  useEffect(() => {
    if (params && value == null) onChange(params.default_duration);
  }, [params, value, onChange]);

  const options = useMemo(() => {
    if (!params) return [];
    // У Seedance 2.5 допустимы все секунды 4..30 — это 27 пунктов, слишком
    // длинный список. Показываем разумную сетку, всегда включая минимум,
    // максимум и текущее значение.
    const all = params.durations;
    if (all.length <= 8) return all;
    const preferred = [4, 5, 6, 8, 10, 15, 20, 25, 30];
    const picked = all.filter((d) => preferred.includes(d));
    const set = new Set<number>([all[0], all[all.length - 1], ...picked]);
    if (value != null && all.includes(value)) set.add(value);
    return Array.from(set).sort((a, b) => a - b);
  }, [params, value]);

  if (!params || options.length < 2) return null;

  const perSec = Number(params.credits_per_second) || 0;
  const current = value ?? params.default_duration;
  const cost = Math.max(1, Math.ceil(current * perSec));

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className="inline-flex items-center gap-1 text-xs text-muted shrink-0">
        <FiClock />
        {t("chat.video.duration", { defaultValue: "Длительность" })}
      </span>

      <div className="flex items-center gap-1 flex-wrap">
        {options.map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => onChange(d)}
            aria-pressed={current === d}
            title={t("chat.video.duration_cost", {
              seconds: d,
              credits: Math.max(1, Math.ceil(d * perSec)),
              defaultValue: "{{seconds}} сек — {{credits}} кредитов",
            })}
            className={
              "rounded-full px-2 py-0.5 text-xs font-semibold transition-colors cursor-pointer border " +
              (current === d
                ? "bg-accent text-on-accent border-accent"
                : "bg-surface-2 text-muted border-border hover:text-foreground")
            }
          >
            {d}
            {t("chat.video.sec_short", { defaultValue: "с" })}
          </button>
        ))}
      </div>

      <span className="text-xs text-accent-strong font-semibold shrink-0">
        ≈ {cost} {t("topup.credits", { defaultValue: "кредитов" })}
      </span>
    </div>
  );
}
