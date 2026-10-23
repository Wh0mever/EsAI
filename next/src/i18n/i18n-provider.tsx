'use client';

import { ReactNode, useEffect, useState } from "react";
import { I18nextProvider } from "react-i18next";
import i18n, { initI18n } from "./i18n";

// fallback — то, что уходит в HTML с сервера и показывается, пока переводы грузятся
// (сейчас — скрытый SEO-блок главной с H1, см. components/home/HomeSeoFallback).
// Сервер и первый рендер клиента отдают одно и то же, поэтому гидрация не меняется.
export function I18nProvider({ children, lang, fallback = null }: { children: ReactNode; lang: string; fallback?: ReactNode }) {
	const [ready, setReady] = useState(false);

	useEffect(() => {
		initI18n(lang).then(() => setReady(true));
	}, [lang]);

	if (!ready) return <>{fallback}</>;

	return <I18nextProvider i18n={i18n}>{children}</I18nextProvider>;
}
