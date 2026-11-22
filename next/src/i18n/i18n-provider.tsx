'use client';

import { ReactNode, useEffect, useState } from "react";
import { I18nextProvider } from "react-i18next";
import { usePathname } from "next/navigation";
import type { i18n as I18n, Resource } from "i18next";
import i18n, { addBundles, createServerI18n, enableSuspense, initI18n, initI18nSync } from "./i18n";

type Props = {
	children: ReactNode;
	lang: string;
	/**
	 * Страницы без серверной отрисовки: то, что уходит в HTML и показывается, пока
	 * переводы грузятся (скрытый SEO-блок, см. components/home/HomeSeoFallback).
	 */
	fallback?: ReactNode;
	/**
	 * Словари с сервера (i18n/server.ts): дети рисуются и на сервере, и в браузере
	 * сразу (SSR_ROUTES в i18n/settings.ts). null — старое поведение.
	 */
	resources?: Resource | null;
	ns?: string[];
};

// Сервер и первый рендер браузера отдают одно и то же: решение «с SSR или без»
// принимает только сервер и передаёт его пропсами, поэтому гидрация не расходится.
export function I18nProvider({ children, lang, fallback = null, resources = null, ns = [] }: Props) {
	// Решается ОДИН раз, по первым пропсам, одинаково на сервере и в браузере.
	const [inst] = useState<I18n | null>(() => {
		if (!resources) return null;
		return typeof window === "undefined" ? createServerI18n(lang, resources, ns) : initI18nSync(lang, resources, ns);
	});
	const [ready, setReady] = useState(inst !== null);
	const pathname = usePathname();
	const [initialPath] = useState(pathname);

	// useSuspense включается НЕ после монтирования: эффект провайдера срабатывает, когда
	// закоммичена только оболочка, а страница под границей loading.tsx (и вложенные
	// Suspense) гидратируется позже, отдельным проходом React (OffscreenLane). Включи мы
	// его в эффекте — страница гидратировалась бы уже с useSuspense=true, и пространство
	// имён, которого нет в SSR_ROUTES, «подвесило» бы границу: мёртвый серверный HTML,
	// затем расхождение текста (июльский класс «кнопки не нажимаются»).
	// Поэтому — при первой клиентской навигации (путь сменился; при гидрации он равен
	// исходному). Прямо в рендере: провайдер рисуется раньше детей, и новая страница уже
	// в этом же проходе при недостающем пространстве имён показывает loading.tsx, а не
	// ключи. Повторный вызов безвреден (просто ставит true).
	if (inst && pathname !== initialPath) enableSuspense(inst);

	useEffect(() => {
		if (inst) return;
		initI18n(lang).then(() => setReady(true)); // старый путь — без изменений
	}, [inst, lang]);

	// Язык в пропсах сменился (корневой layout перерисован сервером) — словари уже пришли.
	useEffect(() => {
		if (!inst || inst.language === lang) return;
		if (resources) addBundles(inst, resources);
		void inst.changeLanguage(lang);
	}, [inst, lang, resources]);

	if (!ready) return <>{fallback}</>;

	return <I18nextProvider i18n={inst ?? i18n}>{children}</I18nextProvider>;
}
