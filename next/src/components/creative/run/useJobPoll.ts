"use client";

import { useEffect, useRef, useState } from "react";
import { getJob, isOpen, type JobJSON } from "@/lib/creative/api";

/**
 * Опрос одной работы, пока она не закончится (SPEC_B §9).
 *
 * Первые две минуты — раз в 3 с, дальше раз в 5 с; при сбое сети — 6 → 12 →
 * 24 → 30 с, на 429 — 15 с. На скрытой вкладке не опрашиваем: вернулся —
 * спросим сразу. Работа закончилась — событие balance:refresh (шапка и
 * напоминание об остатке перечитают баланс) и onSettled.
 */
const FAST_MS = 3000;
const SLOW_MS = 5000;
const FAST_FOR_MS = 120_000;
const BACKOFF_MS = [6000, 12000, 24000, 30000];
const THROTTLED_MS = 15000;

export function useJobPoll(
  initial: JobJSON | null,
  onSettled?: (job: JobJSON) => void,
): readonly [JobJSON | null, (job: JobJSON | null) => void] {
  const [job, setJob] = useState<JobJSON | null>(initial);
  const [seed, setSeed] = useState(initial);
  if (seed !== initial) {
    // Новая работа с той же страницы (запуск, «ещё раз», восстановление) — начинаем с неё.
    setSeed(initial);
    setJob(initial);
  }
  const settledRef = useRef(onSettled);
  useEffect(() => {
    settledRef.current = onSettled;
  });

  const uid = job?.uid ?? null;
  const open = isOpen(job?.status);

  useEffect(() => {
    if (!uid || !open) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let failures = 0;
    let busy = false;
    const started = Date.now();

    const schedule = (ms: number) => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(tick, ms);
    };
    const tick = async () => {
      timer = null;
      if (!alive || busy) return;
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      busy = true;
      const r = await getJob(uid);
      busy = false;
      if (!alive) return;
      if (r.ok) {
        failures = 0;
        setJob(r.data);
        if (!isOpen(r.data.status)) {
          try {
            window.dispatchEvent(new CustomEvent("balance:refresh"));
          } catch {
            /* старый браузер */
          }
          settledRef.current?.(r.data);
          return;
        }
        schedule(Date.now() - started < FAST_FOR_MS ? FAST_MS : SLOW_MS);
        return;
      }
      const code = r.error.code;
      // Работу не найти или вход/раздел закрыт — опрашивать бессмысленно.
      if (code === "job_not_found" || r.status === 401 || r.status === 403) return;
      if (r.status === 429) {
        schedule(THROTTLED_MS);
        return;
      }
      schedule(BACKOFF_MS[Math.min(failures, BACKOFF_MS.length - 1)]);
      failures += 1;
    };
    const wake = () => {
      if (document.visibilityState === "visible" && !busy) schedule(0);
    };
    schedule(FAST_MS);
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("online", wake);
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", wake);
      window.removeEventListener("online", wake);
    };
  }, [uid, open]);

  return [job, setJob] as const;
}
