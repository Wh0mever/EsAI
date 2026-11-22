import ru from "@/locales/ru/common.json";
import en from "@/locales/en/common.json";
import kg from "@/locales/kg/common.json";
import { VSTUDIO_NAV } from "@/lib/nav/menu";

// Что видит чат /chat в HTML с сервера, пока в браузере грузятся переводы.
// (До этапа A6 этот блок отдавала главная «/», когда главной был чат.)
//
// I18nProvider рендерит детей только после асинхронной загрузки переводов
// (синхронная инициализация в июле 2026 ломала гидрацию — «мёртвая гидрация»,
// см. i18n-provider.tsx), поэтому HTML с сервера пустой: анализаторы ссылок и
// краулеры без JS не находили бы на странице ни H1, ни текста. Этот блок
// отдаётся вместо детей до готовности переводов и исчезает, когда появляется
// настоящий HomeHero чата со своим H1, — заголовок H1 на странице всегда один.
// Визуально скрыт (sr-only): человек видит пустой кадр долю секунды, а не
// вспышку неоформленного текста.

type Dict = { home?: { hero?: { title?: string; tagline?: string; subtitle?: string } } };

const DICTS: Record<string, Dict> = { ru, en, kg };

type Section = { href: string; label: string; vstudio?: boolean };

const SECTIONS: Record<string, Section[]> = {
	ru: [
		{ href: "/", label: "Главная" },
		{ href: "/studio", label: "Мультстудия" },
		{ href: "/video-studio", label: "Видеостудия", vstudio: true },
		{ href: "/merge", label: "Склейка видео" },
		{ href: "/academy", label: "EsAI Академия" },
		{ href: "/pricing", label: "Цены" },
	],
	en: [
		{ href: "/", label: "Home" },
		{ href: "/studio", label: "Cartoon studio" },
		{ href: "/video-studio", label: "Video studio", vstudio: true },
		{ href: "/merge", label: "Video merge" },
		{ href: "/academy", label: "EsAI Academy" },
		{ href: "/pricing", label: "Pricing" },
	],
	kg: [
		{ href: "/", label: "Башкы бет" },
		{ href: "/studio", label: "Мультстудия" },
		{ href: "/video-studio", label: "Видеостудия", vstudio: true },
		{ href: "/merge", label: "Видео бириктирүү" },
		{ href: "/academy", label: "EsAI Академиясы" },
		{ href: "/pricing", label: "Баалар" },
	],
};

export default function ChatSeoFallback({ lang }: { lang: string }) {
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
				{SECTIONS[key]
					.filter((s) => !s.vstudio || VSTUDIO_NAV)
					.map((s) => (
						<li key={s.href}>
							<a href={s.href}>{s.label}</a>
						</li>
					))}
			</ul>
		</div>
	);
}
