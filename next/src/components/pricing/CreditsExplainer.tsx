"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { vendorColorByOpenRouterId } from "@/lib/vendorColors";
import {
  fluxImageCredits,
  isFluxImageModel,
  videoPriceFrom,
  type VideoPriceTable,
} from "@/lib/modelBilling";

/**
 * CreditsExplainer — блок «Как списываются кредиты?» для страницы тарифов.
 * Текст — дословно от владельца продукта. Цены — только с сервера: тариф текста
 * из ai/models/ (markup_coefficient = кредитов за 1000 токенов), картинка FLUX —
 * его же credits_per_image, видео — «от N» из таблицы цен ai/video-params/.
 * Своих чисел витрина не держит: прежний запасной список анонсированных ставок
 * устарел и после смены цен в админке показывал бы чужие цифры.
 */

type ModelRow = {
  name: string;
  openrouter_id?: string;
  markup_coefficient?: number;
  /** Цена картинки FLUX в действующем режиме цен — считает сервер. */
  credits_per_image?: number | null;
  is_free?: boolean;
  sort_order?: number;
  category?: string;
};

type VideoPrices = {
  price_table?: VideoPriceTable;
  price_table_by_aspect?: Record<string, VideoPriceTable>;
};

// «От N» по видео живёт 10 минут, как параметры видео в чате: таблицы
// считаются по прайсу провайдера и курсу и меняются сами.
const VIDEO_TTL_MS = 10 * 60 * 1000;
const videoCache = new Map<string, { at: number; from: number | null }>();

/** Самая дешёвая цена ролика модели; null — сервер цены не дал или не ответил. */
async function loadVideoFrom(openrouterId: string): Promise<number | null> {
  const hit = videoCache.get(openrouterId);
  if (hit && Date.now() - hit.at < VIDEO_TTL_MS) return hit.from;
  try {
    const res = await fetchData<VideoPrices>(
      "ai/video-params/?model=" + encodeURIComponent(openrouterId),
      "GET",
      null,
      false
    );
    // Сбой не кэшируем: следующий показ блока спросит заново.
    if (!res?.ok || !res.data) return null;
    const from = videoPriceFrom(res.data.price_table, res.data.price_table_by_aspect);
    videoCache.set(openrouterId, { at: Date.now(), from });
    return from;
  } catch {
    return null;
  }
}

// Цвета вендоров вынесены в общий next/src/lib/vendorColors.ts — единый
// источник палитры, которым также пользуются home/HomeHero.tsx и
// home/PopularModels.tsx (чтобы FLUX/Kling и остальные вендоры совпадали
// цветом во всех блоках сайта).

export default function CreditsExplainer() {
  const { t } = useTranslation("common");
  // null — список ещё не пришёл; failed — сервер не ответил.
  const [rows, setRows] = useState<ModelRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  // Цена ролика по id модели; ключа нет — ещё не загружали.
  const [videoFrom, setVideoFrom] = useState<Record<string, number | null>>({});
  const videoBox = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchData<ModelRow[]>("ai/models/", "GET", null, false);
        if (cancelled) return;
        const list = res?.ok && Array.isArray(res.data) ? res.data : [];
        const usable = list
          .filter((m) => typeof m.markup_coefficient === "number")
          .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
        setRows(usable);
        setFailed(!usable.length);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // «За картинку» списывают только FLUX (ai/model_billing.flux_charge_credits).
  // Nano Banana тоже category=image, но в чате биллится токенами
  // (ceil(tokens*coeff/1000)) — её коэффициент под шапкой «за картинку» занижал
  // реальную цену (17 вместо ≈25). Поэтому держим её в таблице «за 1000 токенов».
  const kindOf = (m: ModelRow) =>
    m.category === "video"
      ? "video"
      : m.category === "image"
        ? isFluxImageModel(m.openrouter_id) ? "image" : "image_tokens"
        : "text";

  const videoIds = useMemo(
    () =>
      (rows ?? [])
        .filter((m) => m.category === "video" && m.openrouter_id)
        .map((m) => String(m.openrouter_id))
        .join("\n"),
    [rows]
  );

  // Таблицы цен видео запрашиваем, только когда блок видео виден: витрина стоит
  // и на главной, свёрнутой, и десяток запросов на каждого посетителя ради
  // невидимых цифр — лишняя нагрузка и упор в лимит запросов гостя. Свёрнутый
  // блок обрезан родителем (max-height: 0), площадь пересечения у него нулевая.
  useEffect(() => {
    const el = videoBox.current;
    const ids = videoIds ? videoIds.split("\n") : [];
    if (!el || !ids.length) return;
    let alive = true;
    let started = false;
    const load = () => {
      if (started) return;
      started = true;
      void Promise.all(ids.map(async (id) => [id, await loadVideoFrom(id)] as const)).then((pairs) => {
        if (alive) setVideoFrom(Object.fromEntries(pairs));
      });
    };
    if (typeof IntersectionObserver === "undefined") {
      load();
      return () => {
        alive = false;
      };
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.intersectionRatio > 0)) {
          io.disconnect();
          load();
        }
      },
      { threshold: [0.01] }
    );
    io.observe(el);
    return () => {
      alive = false;
      io.disconnect();
    };
  }, [videoIds]);

  const groups = [
    {
      key: "text",
      title: t("packages.credits_table_text", { defaultValue: "Текстовые модели" }),
      unit: t("packages.credits_table_rate", { defaultValue: "Кредитов за 1000 токенов" }),
    },
    {
      key: "image",
      title: t("packages.credits_table_image", { defaultValue: "Картинки" }),
      unit: t("packages.credits_table_rate_image", { defaultValue: "Кредитов за картинку" }),
    },
    {
      key: "image_tokens",
      title: t("packages.credits_table_image_tokens", { defaultValue: "Картинки (по токенам)" }),
      unit: t("packages.credits_table_rate", { defaultValue: "Кредитов за 1000 токенов" }),
    },
    {
      key: "video",
      title: t("packages.credits_table_video", { defaultValue: "Видео" }),
      unit: t("packages.credits_table_rate_video_clip", { defaultValue: "Кредитов за ролик" }),
    },
  ]
    .map((g) => ({ ...g, rows: (rows ?? []).filter((m) => kindOf(m) === g.key) }))
    .filter((g) => g.rows.length > 0);

  const unavailable = t("packages.credits_price_unavailable", { defaultValue: "Цена сейчас недоступна" });

  /** Число в правой колонке: тариф, цена картинки или «от N» за ролик. */
  const priceCell = (kind: string, m: ModelRow) => {
    if (kind === "image") return fluxImageCredits(m);
    if (kind !== "video") return Number(m.markup_coefficient);
    const id = String(m.openrouter_id ?? "");
    if (id && !(id in videoFrom)) {
      return (
        <span className="font-normal text-muted-2">
          <span aria-hidden>…</span>
          <span className="sr-only">{t("packages.credits_price_loading", { defaultValue: "Загружаем цену" })}</span>
        </span>
      );
    }
    const from = id ? videoFrom[id] : null;
    if (from === null) {
      return (
        <span className="font-normal text-muted-2" title={unavailable}>
          <span aria-hidden>—</span>
          <span className="sr-only">{unavailable}</span>
        </span>
      );
    }
    return t("packages.credits_from", { credits: from, defaultValue: "от {{credits}}" });
  };

  return (
    <div className="lg:px-40 px-6 w-full">
      <div className="mt-4 rounded-2xl border border-border bg-surface-2 p-6 md:p-8 flex flex-col gap-4">
        <h3 className="text-2xl font-semibold text-foreground">
          {t("packages.credits_explainer_title", { defaultValue: "Как списываются кредиты?" })}
        </h3>

        <div className="text-muted flex flex-col gap-3 max-w-2xl leading-relaxed">
          <p>
            {t("packages.credits_explainer_p1", {
              defaultValue:
                "Каждая нейросеть расходует кредиты по-разному. Чем мощнее модель, тем больше кредитов расходуется за один и тот же объём текста.",
            })}
          </p>
          <p>
            {t("packages.credits_explainer_p2", {
              defaultValue:
                "Например, если задать один и тот же вопрос разным нейросетям, расход кредитов будет отличаться.",
            })}
          </p>
          <p>
            {t("packages.credits_explainer_p3", {
              defaultValue: "Точное количество списанных кредитов зависит от длины вашего запроса и ответа нейросети.",
            })}
          </p>
          <p>
            {t("packages.credits_explainer_p4", {
              defaultValue: "После каждого ответа вы сразу видите, сколько кредитов было списано именно за этот запрос.",
            })}
          </p>
        </div>

        {failed && (
          <p className="text-sm text-muted-2">
            {t("packages.credits_load_failed", {
              defaultValue: "Цены моделей сейчас не загрузились. Точную цену вы всегда увидите перед генерацией.",
            })}
          </p>
        )}

        {/* Тариф по моделям — отдельными таблицами: у текста и токенных картинок
            цена за 1000 токенов, у FLUX — за картинку, у видео — за ролик. В одной
            таблице под шапкой «за 1000 токенов» видео читалось как «Veo — 83 за 1000 токенов». */}
        {groups.map((g) => (
          <div
            key={g.key}
            ref={g.key === "video" ? videoBox : undefined}
            className="mt-2 overflow-hidden rounded-xl border border-border"
          >
            <div className="grid grid-cols-[1fr_auto] items-center gap-2 bg-surface px-4 py-2.5 text-xs uppercase tracking-wide text-muted-2">
              <span>{g.title}</span>
              <span className="text-right">{g.unit}</span>
            </div>
            <ul className="divide-y divide-border">
              {g.rows.map((m) => (
                <li
                  key={m.openrouter_id || m.name}
                  className="grid grid-cols-[1fr_auto] items-center gap-2 px-4 py-3"
                >
                  <span className="flex items-center gap-2.5 min-w-0">
                    <span
                      className="h-2.5 w-2.5 rounded-full shrink-0"
                      style={{ background: vendorColorByOpenRouterId(m.openrouter_id) }}
                    />
                    <span className="truncate text-foreground">{m.name}</span>
                    {m.is_free && (
                      <span className="shrink-0 rounded-md bg-accent/15 px-1.5 py-0.5 text-[11px] font-medium text-accent-strong">
                        {t("packages.credits_free_badge", { defaultValue: "бесплатная" })}
                      </span>
                    )}
                  </span>
                  <span className="text-right tabular-nums font-semibold text-foreground">
                    {priceCell(g.key, m)}
                  </span>
                </li>
              ))}
            </ul>
            {/* Видео — «от N»: тариф модели не цена, ролик стоит по себестоимости
                провайдера, и длиннее или в 1080p он дороже — говорим заранее. */}
            {g.key === "video" && (
              <p className="border-t border-border px-4 py-2.5 text-xs text-muted-2">
                {t("packages.credits_video_note_from", {
                  defaultValue:
                    "«От» — самый дешёвый ролик модели: самый короткий, в самом простом качестве. Длиннее и в 1080p дороже — точную цену вы увидите перед съёмкой.",
                })}
              </p>
            )}
          </div>
        ))}

        <p className="text-xs text-muted-2">
          {t("packages.credits_free_note", {
            defaultValue:
              "«Бесплатная» — модель доступна без оплаты на стартовом балансе; кредиты за ответ всё равно списываются по её тарифу. Премиум-модели доступны после пополнения баланса.",
          })}
        </p>
      </div>
    </div>
  );
}
