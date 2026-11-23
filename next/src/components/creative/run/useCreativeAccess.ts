"use client";

import { useEffect, useSyncExternalStore } from "react";
import { getTools, type ToolAccess, type ToolsResponse } from "@/lib/creative/api";
import { getToken } from "@/tools/fetchData";

/**
 * GET /api/creative/tools/ — режим раздела и доступность инструментов.
 *
 * Один снимок на вкладку (модульное хранилище): каталог, страница инструмента и
 * «Мои работы» не спрашивают сервер каждый раз. Снимок привязан к токену входа:
 * вошёл/вышел — спросим заново. На сервере и при гидрации — «ещё не знаем»
 * (одинаковый первый кадр), данные приходят после монтирования.
 */
export type AccessState =
  | { status: "loading"; data: null }
  | { status: "ready"; data: ToolsResponse }
  | { status: "error"; data: null };

const TTL_MS = 60_000;
const LOADING: AccessState = { status: "loading", data: null };

let snapshot: AccessState = LOADING;
let fetchedAt = 0;
let identity: string | null = null;
let inflight: Promise<void> | null = null;
const listeners = new Set<() => void>();

function emit(next: AccessState) {
  snapshot = next;
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

/** Запросить снимок (если устарел, сменился вход или force). */
export function refreshAccess(force = false): Promise<void> {
  const who = getToken("access") || "";
  const fresh = snapshot.status === "ready" && identity === who && Date.now() - fetchedAt < TTL_MS;
  if (!force && fresh) return Promise.resolve();
  if (inflight) return inflight;
  inflight = getTools()
    .then((r) => {
      identity = getToken("access") || "";
      fetchedAt = Date.now();
      emit(r.ok ? { status: "ready", data: r.data } : { status: "error", data: null });
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

export function useCreativeAccess(): AccessState {
  const state = useSyncExternalStore(subscribe, () => snapshot, () => LOADING);
  useEffect(() => {
    void refreshAccess();
  }, []);
  return state;
}

/** Что показать на странице инструмента. */
export type ToolGate =
  | { kind: "checking" }
  | { kind: "soon" }
  /** форма: run — вошёл и может запускать; guest — превью формы с кнопкой входа */
  | { kind: "form"; run: boolean; tool: ToolAccess | null; data: ToolsResponse };

export function toolGate(state: AccessState, toolId: string, authed: boolean): ToolGate {
  if (state.status === "loading") return { kind: "checking" };
  if (state.status === "error") return { kind: "soon" };
  const data = state.data;
  const tool = data.tools.find((t) => t.id === toolId) ?? null;
  if (tool && !tool.enabled) return { kind: "soon" };
  if (data.available) return { kind: "form", run: true, tool, data };
  // Гость видит форму, только когда раздел открыт всем; иначе — «Скоро».
  if (!authed && data.mode === "on") return { kind: "form", run: false, tool, data };
  return { kind: "soon" };
}
