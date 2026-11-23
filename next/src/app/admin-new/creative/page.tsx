"use client";

import { useCallback, useEffect, useState } from "react";
import { FiAperture, FiRefreshCw } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import { CARD, Notices, Skeleton, btn, useNotices } from "../vstudio-showcase/parts";
import {
  SETTINGS_PATH,
  errorText,
  isSuperuserRefusal,
  parseSettings,
  type Settings,
} from "./creativeAdmin";
import { MarkupCard, ModeCard, ToolsCard, type PatchResult } from "./SettingsCards";
import { LogCard, SummaryCard } from "./ReportCards";

/**
 * Creative Studio в админке (SPEC_B §8): режим раздела, общая наценка,
 * по инструментам — рубильник и своя наценка с примером цены, сводка за
 * период и журнал изменений.
 *
 * Настройки грузятся один раз и обновляются ответом каждого сохранения
 * (сервер присылает их целиком), сводка и журнал грузятся сами. Разбор
 * ответов и формулы — в creativeAdmin.ts, его проверяет node-тест.
 * Названия инструментов — наши, поставщика в админке не называем: этот
 * код уходит в браузер.
 */
export default function AdminCreativePage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [tick, setTick] = useState(0);
  const [loaded, setLoaded] = useState<{ tick: number; error: string | null } | null>(null);
  // Сервер отказал в деньгах (403 superuser_required) — денежные поля выключаем.
  const [moneyLocked, setMoneyLocked] = useState(false);
  const [logTick, setLogTick] = useState(0);
  const { list, notify, close } = useNotices();

  const loading = loaded?.tick !== tick;
  const error = loading ? null : (loaded?.error ?? null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<unknown>(SETTINGS_PATH, "GET", null, true);
      if (!alive) return;
      const parsed = res.ok ? parseSettings(res.data) : null;
      if (!parsed) {
        setLoaded({
          tick,
          error: res.ok ? "Сервер ответил непонятно. Обновите страницу." : errorText(res, "Настройки не загрузились"),
        });
        return;
      }
      setSettings(parsed);
      setLoaded({ tick, error: null });
    })();
    return () => {
      alive = false;
    };
  }, [tick]);

  /** PATCH настроек: ответ — настройки целиком; журнал перечитываем. */
  const patch = useCallback(
    async (body: Record<string, unknown>, okText: string): Promise<PatchResult> => {
      const res = await fetchData<unknown>(SETTINGS_PATH, "PATCH", body, true);
      const parsed = res.ok ? parseSettings(res.data) : null;
      if (parsed) {
        setSettings(parsed);
        setLogTick((t) => t + 1);
        notify("ok", okText);
        return { ok: true };
      }
      if (isSuperuserRefusal(res)) setMoneyLocked(true);
      return {
        ok: false,
        error: res.ok
          ? "Сохранено, но ответ сервера непонятен — обновите страницу."
          : errorText(res, "Не удалось сохранить"),
      };
    },
    [notify],
  );

  const canEditMoney = settings !== null && settings.canEditMoney !== false && !moneyLocked;

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2">
          <FiAperture className="h-5 w-5 text-accent" aria-hidden />
          <h1 className="text-2xl font-semibold">Creative Studio</h1>
        </div>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          15 инструментов раздела /creative: кому он открыт, сколько стоит каждый инструмент в кредитах, сколько
          задач прошло и что на них заработано. Всё применяется сразу после сохранения.
        </p>
      </div>

      {!settings && loading && (
        <div className="space-y-4" aria-busy="true">
          <Skeleton className="h-36" />
          <Skeleton className="h-44" />
          <Skeleton className="h-96" />
        </div>
      )}

      {!settings && error && (
        <div className={`${CARD} flex flex-col items-start gap-3 p-6`}>
          <div role="alert" className="text-sm text-status-fail">
            {error}
          </div>
          <button type="button" onClick={() => setTick((t) => t + 1)} className={btn("plain", "lg")}>
            <FiRefreshCw className="h-4 w-4" aria-hidden />
            Повторить
          </button>
        </div>
      )}

      {settings && (
        <>
          <ModeCard settings={settings} onPatch={patch} />
          <MarkupCard settings={settings} canEditMoney={canEditMoney} onPatch={patch} />
          <ToolsCard
            settings={settings}
            canEditMoney={canEditMoney}
            onPatch={patch}
            onFail={(text) => notify("fail", text)}
          />
        </>
      )}

      <SummaryCard />
      <LogCard tools={settings?.tools ?? []} defaultPct={settings?.markupDefaultPct ?? "40"} reload={logTick} />

      <Notices list={list} onClose={close} />
    </div>
  );
}
