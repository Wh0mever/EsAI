import ru from "@/locales/ru/common.json";
import en from "@/locales/en/common.json";
import kg from "@/locales/kg/common.json";

// Что видит главная в HTML с сервера, пока в браузере грузятся переводы.
//
// I18nProvider рендерит детей только после асинхронной загрузки переводов
// (синхронная инициализация в июле 2026 ломала гидрацию — «мёртвая гидрация»,
// см. i18n-provider.tsx), поэтому HTML с сервера пустой: анализаторы ссылок и
// краулеры без JS не находили на главной ни H1, ни текста. Этот блок отдаётся
// вместо детей до готовности переводов и исчезает, когда появляется настоящий
// HomeHero со своим H1, — заголовок H1 на странице всегда один.
// Визуально скрыт (sr-only): человек, как и раньше, видит пустой кадр долю
// секунды, а не вспышку неоформленного текста.

type Dict = { home?: { hero?: { title?: string; tagline?: string; subtitle?: string } } };

const DICTS: Record<string, Dict> = { ru, en, kg };

const SECTIONS: Record<string, { href: string; label: string }[]> = {
	ru: [
		{ href: "/studio", label: "Мультстудия" },
		{ href: "/video-studio", label: "Видеостудия" },
		{ href: "/merge", label: "Склейка видео" },
		{ href: "/academy", label: "EsAI Академия" },
		{ href: "/pricing", label: "Цены" },
	],
	en: [
		{ href: "/studio", label: "Cartoon studio" },
		{ href: "/video-studio", label: "Video studio" },
		{ href: "/merge", label: "Video merge" },
		{ href: "/academy", label: "EsAI Academy" },
		{ href: "/pricing", label: "Pricing" },
	],
	kg: [
		{ href: "/studio", label: "Мультстудия" },
		{ href: "/video-studio", label: "Видеостудия" },
		{ href: "/merge", label: "Видео бириктирүү" },
		{ href: "/academy", label: "EsAI Академиясы" },
		{ href: "/pricing", label: "Баалар" },
	],
};

export default function HomeSeoFallback({ lang }: { lang: string }) {
	const key = lang in DICTS ? lang : "ru";
	const hero = DICTS[key].home?.hero ?? {};
	const title = hero.title || "Все лучшие нейросети мира в одном месте";
	const tagline = hero.tagline || "";
	return (
		<div className="sr-only">
			<h1>
				{title}
				{tagline ? ` ${tagline}` : ""}
			</h1>
			{hero.subtitle ? <p>{hero.subtitle}</p> : null}
			<ul>
				{SECTIONS[key].map((s) => (
					<li key={s.href}>
						<a href={s.href}>{s.label}</a>
					</li>
				))}
			</ul>
		</div>
	);
}
