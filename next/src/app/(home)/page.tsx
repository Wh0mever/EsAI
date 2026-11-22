import "@/assets/style.scss";
import type { Metadata } from "next";
import { preload } from "react-dom";
import HomeHub from "@/components/landing/HomeHub";
import { CREATIVE_NAV } from "@/lib/nav/menu";
import { OG_IMAGE, OG_IMAGE_ALT, OG_IMAGE_META, SITE_NAME, SITE_URL } from "@/lib/seo/site";

// Главная — хаб платформы (этап A6). Заголовок и описание чата переехали на /chat (A1).
// Canonical главной живёт здесь, а не в корневом layout — иначе его наследовали
// все страницы без собственного canonical.
// TITLE = hub.meta_title из locales/ru/creative.json.
const TITLE = "EsAI — всё для творчества и работы с ИИ: чат, видео, мультфильмы, изображения";
const SHORT = "EsAI — всё для творчества и работы с ИИ";
const DESCRIPTION = CREATIVE_NAV
	? "Чаты с ChatGPT, Claude, Gemini и DeepSeek, Мультстудия, Видеостудия, Creative Studio (15 AI-инструментов) и бесплатная склейка видео — в одном аккаунте. Без подписок, оплата в сомах."
	: "Чаты с ChatGPT, Claude, Gemini и DeepSeek, Мультстудия — мультфильмы с вашим героем, Видеостудия и бесплатная склейка видео — в одном аккаунте. Без подписок, оплата в сомах.";

export const metadata: Metadata = {
	title: TITLE,
	description: DESCRIPTION,
	alternates: { canonical: "/" },
	// openGraph/twitter в Next заменяют родительские целиком — картинки повторены.
	openGraph: {
		images: [OG_IMAGE_META],
		title: SHORT,
		description: DESCRIPTION,
		url: SITE_URL,
		siteName: SITE_NAME,
		type: "website",
	},
	twitter: {
		card: "summary_large_image",
		title: SHORT,
		description: DESCRIPTION,
		images: [{ url: OG_IMAGE, alt: OG_IMAGE_ALT }],
	},
};

export default function Home() {
	// Кот на первом экране — LCP. Хаб приходит с сервера целиком (i18n/settings.ts,
	// SSR_ROUTES), подсказка всё равно полезна: картинка грузится с самого начала
	// <head>, а при I18N_SSR=off хаб снова рисуется только после загрузки переводов.
	preload("/images/home/cat-esai-m-800.webp", { as: "image", fetchPriority: "high", media: "(max-width: 767px)" });
	preload("/images/home/cat-esai-1280.webp", {
		as: "image",
		fetchPriority: "high",
		imageSrcSet: "/images/home/cat-esai-768.webp 768w, /images/home/cat-esai-1280.webp 1280w",
		imageSizes: "(min-width: 1280px) 1280px, 100vw",
		media: "(min-width: 768px)",
	});
	return <HomeHub />;
}
