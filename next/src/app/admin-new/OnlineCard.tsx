"use client";

import { useEffect, useState } from "react";
import { fetchData } from "@/tools/fetchData";

/** Сколько человек на сайте прямо сейчас — GET manage/online/, обновление раз в 15 с. */

type Online = {
  online: number;
  users: number;
  guests: number;
  by_section: Record<string, number>;
  peak_today: number;
  window_sec: number;
};

const SECTION_LABELS: [string, string][] = [
  ["chat", "Чат"],
  ["video_studio", "Видеостудия"],
  ["studio", "Мультстудия"],
  ["merge", "Склейка"],
  ["pricing", "Тарифы"],
  ["other", "Другие страницы"],
];

const REFRESH_MS = 15_000;
const nf = (n: number) => (n ?? 0).toLocaleString("ru-RU");

export default function OnlineCard() {
  const [data, setData] = useState<Online | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      if (document.visibilityState !== "visible") return;
      const res = await fetchData<Online>("manage/online/", "GET", null, true);
      if (!alive) return;
      if (res.ok && res.data) {
        setData(res.data);
        setFailed(false);
      } else setFailed(true);
    };
    void load();
    const timer = window.setInterval(() => void load(), REFRESH_MS);
    const onVisible = () => document.visibilityState === "visible" && void load();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  return (
    <section className="rounded-2xl border border-border bg-surface p-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-sm text-muted">
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-400" />
            </span>
            Онлайн сейчас
          </div>
          <div className="mt-2 text-4xl font-semibold tracking-tight">{data ? nf(data.online) : "—"}</div>
          <div className="mt-1 text-xs text-muted-2">
            {data
              ? `вошедших: ${nf(data.users)} · гостей: ${nf(data.guests)} · пик сегодня: ${nf(data.peak_today)}`
              : failed
              ? "не удалось загрузить"
              : "загрузка…"}
          </div>
        </div>
        {data && (
          <div className="flex flex-wrap gap-2">
            {SECTION_LABELS.map(([key, label]) => (
              <div key={key} className="rounded-xl border border-border bg-surface-2 px-3 py-2 text-center">
                <div className="text-lg font-semibold leading-tight">{nf(data.by_section[key] || 0)}</div>
                <div className="text-[11px] text-muted-2">{label}</div>
              </div>
            ))}
          </div>
        )}
      </div>
      <p className="mt-3 text-[11px] text-muted-2">
        Открытые на экране вкладки за последние {data ? Math.round(data.window_sec / 60) : 2} мин. Один человек с
        несколькими вкладками — один онлайн. Обновляется каждые 15 секунд.
      </p>
    </section>
  );
}
