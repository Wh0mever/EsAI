import ru from "@/locales/ru/creative.json";
import en from "@/locales/en/creative.json";
import kg from "@/locales/kg/creative.json";
import homeRu from "@/locales/ru/home.json";
import homeEn from "@/locales/en/home.json";
import homeKg from "@/locales/kg/home.json";
import { MAIN_TAIL, STUDIOS, TOOLS, type MenuItem } from "@/lib/nav/menu";

// Что видит главная «/» (хаб платформы, этап A6) в HTML с сервера, пока в
// браузере грузятся переводы. Фолбэк чата — components/chat/ChatSeoFallback.
//
// I18nProvider рендерит детей только после асинхронной загрузки переводов
// (синхронная инициализация в июле 2026 ломала гидрацию — «мёртвая гидрация»,
// см. i18n-provider.tsx), поэтому HTML с сервера пустой: анализаторы ссылок и
// краулеры без JS не находили бы на главной ни H1, ни текста. Этот блок
// отдаётся вместо детей до готовности переводов и исчезает, когда появляется
// настоящий HomeHub. H1 совпадает с H1 хаба (hub.title_a + title_b + title_c) —
// заголовок H1 на странице всегда один. Визуально скрыт (sr-only).
// Ссылки — те же разделы, что в шапке и подвале (lib/nav/menu, с учётом флагов).
//
// С серверной отрисовкой (i18n/settings.ts, SSR_ROUTES) настоящий хаб уже в HTML,
// и корневой layout этот блок не отдаёт (два H1 не нужны). Нужен он только при
// выключателе I18N_SSR=off — тогда всё как раньше.

type Hub = { hub?: { title_a?: string; title_b?: string; title_c?: string; subtitle?: string } };
type Nav = { nav?: Record<string, string> };

const HUB: Record<string, Hub> = { ru, en, kg };
const NAV: Record<string, Nav> = { ru: homeRu, en: homeEn, kg: homeKg };
// Фильтры категорий /creative?cat=… — не отдельные страницы, в список не берём.
const LINKS: MenuItem[] = [...STUDIOS, ...TOOLS.filter((i) => !i.href.includes("?cat=")), ...MAIN_TAIL];

export default function HomeSeoFallback({ lang }: { lang: string }) {
	const key = lang in HUB ? lang : "ru";
	const h = HUB[key].hub ?? {};
	const nav = NAV[key].nav ?? {};
	const title = [h.title_a, h.title_b, h.title_c].filter(Boolean).join(" ") || "Всё для творчества и работы с ИИ";
	return (
		<div className="sr-only">
			<h1>{title}</h1>
			{h.subtitle ? <p>{h.subtitle}</p> : null}
			<ul>
				{LINKS.map((i) => (
					<li key={i.href + i.label}>
						<a href={i.href}>{nav[i.label.replace(/^nav\./, "")] || i.fallback}</a>
					</li>
				))}
			</ul>
		</div>
	);
}
