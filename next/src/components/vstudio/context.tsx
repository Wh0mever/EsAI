"use client";

/**
 * Видеостудия: контекст контейнера (VideoStudio.tsx).
 *
 * Все части студии (композер, параметры, лента, библиотека) читают стор и
 * шлют действия отсюда, а не через цепочку пропсов. Кроме стора контекст
 * даёт общие ручки: вход для гостя, реакция на ошибку API, тост, переход
 * между проектами и контейнер прокрутки ленты.
 */
import { createContext, useContext } from "react";
import type { Dispatch, RefObject } from "react";
import type { ErrorReaction } from "@/lib/vstudio/errors";
import type { PaywallContext } from "@/components/chat/PaywallModal";
import type { ProjectJSON, Toast, Uid, VsAction, VsError, VsState } from "@/lib/vstudio/types";

/** Ширина окна по §9.2: <768, 768–1023, 1024–1279, ≥1280. */
export type VsBreakpoint = "mobile" | "tablet" | "laptop" | "desktop";

export type HandleErrorOptions = {
  /** Не показывать тост для веток message/retry_later (вызывающий покажет свой текст). */
  silent?: boolean;
};

export type VStudioActions = {
  /**
   * Действие только для вошедших («Загрузить», «Создать картинку», «Создать»).
   * Гостю открывает окно входа (событие vstudio_auth_prompt) и сохраняет
   * черновик; true — можно продолжать.
   */
  requireAuth: () => boolean;
  /**
   * Общая реакция на ошибку API: пэйволл, окно входа, «студия закрыта»,
   * офлайн, тост с текстом. Ветки requote / blocked / limit / upload /
   * not_found вызывающий обрабатывает сам по возвращённой реакции.
   * Воронку vstudio_paywall здесь не шлём — это делает тот, кто запускал.
   */
  handleError: (err: VsError, opts?: HandleErrorOptions) => ErrorReaction;
  /** Всплывающее сообщение (уже переведённый текст). take — клик прокрутит к карточке. */
  toast: (text: string, tone?: Toast["tone"], take?: Uid | null) => void;
  /** Открыть проект (null — новая генерация). take — прокрутить к карточке дубля. */
  openProject: (uid: Uid | null, opts?: { take?: Uid | null }) => void;
  /** «+ Новая генерация»: пустая лента, пустой композер (модель и параметры остаются). */
  newSession: () => void;
  renameProject: (uid: Uid, title: string) => Promise<boolean>;
  archiveProject: (uid: Uid) => Promise<boolean>;
  /** Поиск по истории (левая колонка сама выдерживает паузу между буквами). */
  searchProjects: (q: string) => void;
  /** Следующая страница истории (левая колонка). */
  loadMoreProjects: () => Promise<void>;
  /** «Показать раньше» в ленте: страница кадров старше загруженных. */
  loadOlderShots: () => Promise<void>;
  /** Сохранить проект из ответа сервера (PATCH settings, run/done и т. п.). */
  upsertProject: (project: ProjectJSON) => void;
  /** «Мои материалы»: нижняя шторка библиотеки (ui.panels.library). Гостю — окно входа. */
  openLibrary: () => void;
  openPaywall: (paywall: PaywallContext) => void;
  openTopUp: () => void;
  /** Перечитать баланс (useBalance слушает событие balance:refresh). */
  refreshBalance: () => void;
};

export type VStudioContextValue = {
  state: VsState;
  dispatch: Dispatch<VsAction>;
  actions: VStudioActions;
  /** null — ещё проверяем токен. */
  authed: boolean | null;
  /** Баланс из useBalance (null — гость или ещё не пришёл). */
  balance: number | null;
  /** Кредиты в резерве («ждут результата»): из последнего quote/запуска, с поправкой на закрытые дубли. */
  reserved: number;
  online: boolean;
  breakpoint: VsBreakpoint;
  /** uid проекта из адреса (/video-studio/<uid>); null — новая генерация. */
  routeProject: Uid | null;
  /** Контейнер прокрутки ленты: IntersectionObserver «показать раньше» и автопрокрутка вниз. */
  feedScrollRef: RefObject<HTMLDivElement | null>;
};

export const VStudioContext = createContext<VStudioContextValue | null>(null);

/** Контекст студии; вне <VideoStudio> — ошибка разработчика, а не пустое значение. */
export function useVStudio(): VStudioContextValue {
  const ctx = useContext(VStudioContext);
  if (!ctx) throw new Error("useVStudio: компонент должен быть внутри <VideoStudio>");
  return ctx;
}

/** То же, но без ошибки: для компонентов, которые умеют жить и вне студии (витрины, тесты вёрстки). */
export function useVStudioOptional(): VStudioContextValue | null {
  return useContext(VStudioContext);
}
