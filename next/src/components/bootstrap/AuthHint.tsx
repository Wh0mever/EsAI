"use client";

import { createContext, useContext, useSyncExternalStore, type ReactNode } from "react";
import { getToken } from "@/tools/fetchData";
import { isJwtValid } from "@/tools/jwt";

/**
 * Подсказка «вошёл ли посетитель» для первого кадра.
 *
 * Сервер не видит localStorage, но видит cookie access: middleware кладёт ответ в
 * заголовок x-esai-authed, корневой layout — сюда. Это только подсказка для
 * разметки (никакие права от неё не зависят); окончательно решает ensureAccess().
 *
 * useAuthedHint() отдаёт:
 *  - на сервере и при гидрации — подсказку сервера, поэтому HTML и первый рендер
 *    браузера совпадают (без «Hydration failed»);
 *  - сразу после гидрации и при обычном монтировании в браузере — живую cookie
 *    (useSyncExternalStore сам перерисует, если она расходится с подсказкой).
 * Вошедший не видит кадра с «Войти»/«Начать бесплатно», гость — кадра с балансом.
 */
const AuthHintContext = createContext(false);

export function AuthHintProvider({ value, children }: { value: boolean; children: ReactNode }) {
	return <AuthHintContext.Provider value={value}>{children}</AuthHintContext.Provider>;
}

const noopSubscribe = () => () => {};
const cookieAuthed = () => isJwtValid(getToken("access"));

export function useAuthedHint(): boolean {
	const hint = useContext(AuthHintContext);
	return useSyncExternalStore(noopSubscribe, cookieAuthed, () => hint);
}
