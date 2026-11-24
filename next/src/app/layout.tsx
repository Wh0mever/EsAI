import { cookies, headers } from "next/headers";
import { I18nProvider } from "@/i18n/i18n-provider";
import type { Metadata, Viewport } from "next";
import BackToTopButton from "@/components/ui/toTop/BackToTop";
import EdgeThemeToggle from "@/components/theme/EdgeThemeToggle";
import PwaManager from "@/components/pwa/PwaManager";
import LowBalanceNotice from "@/components/billing/LowBalanceNotice";
import PresencePing from "@/components/bootstrap/PresencePing";
import "./globals.css";
import "highlight.js/styles/github-dark.css";
import "@/assets/style.scss";
import DomainDefaults from "@/components/bootstrap/DomainDefaults";
import { THEME_BOOTSTRAP } from "@/lib/theme";
import { CSS_GUARD } from "@/lib/cssGuard";
import { SITE_URL, SITE_NAME, SITE_DESCRIPTION, OG_IMAGE, OG_IMAGE_ALT, OG_IMAGE_META } from "@/lib/seo/site";
import HomeSeoFallback from "@/components/home/HomeSeoFallback";
import ChatSeoFallback from "@/components/chat/ChatSeoFallback";
import AcademySeoFallback from "@/components/academy/AcademySeoFallback";
import { homeJsonLd } from "@/lib/seo/jsonLd";
import { localeFromAcceptLanguage } from "@/lib/localeDetect";
import { i18nSsrEnabled, routeI18n, type Language } from "@/i18n/settings";
import { loadI18nResources } from "@/i18n/server";
import { AuthHintProvider } from "@/components/bootstrap/AuthHint";

export const viewport: Viewport = {
	width: "device-width",
	initialScale: 1,
	viewportFit: "cover",
	themeColor: [
		{ media: "(prefers-color-scheme: dark)", color: "#141414" },
		{ media: "(prefers-color-scheme: light)", color: "#f7f7f5" },
	],
};

export const metadata: Metadata = {
	metadataBase: new URL(SITE_URL),
	manifest: "/manifest.webmanifest",
	applicationName: "EsAI",
	appleWebApp: {
		capable: true,
		statusBarStyle: "black-translucent",
		title: "EsAI",
	},
	title: "EsAI — Все AI в одном месте",
	description: SITE_DESCRIPTION,
	keywords: [
		"EsAI",
		"нейросети онлайн",
		"чат gpt на русском",
		"чат gpt на кыргызском",
		"ChatGPT",
		"DeepSeek",
		"Claude",
		"Gemini",
		"Grok",
		"Perplexity",
		"искусственный интеллект",
		"нейросеть онлайн без VPN",
		"AI чат на русском",
		"нейросеть для текста",
		"нейросеть для кода",
		"оплата в сомах",
	],
	icons: {
		icon: [
			{ url: "/esai-mark.svg", type: "image/svg+xml" },
			{ url: "/icon-192.png", sizes: "192x192", type: "image/png" },
			{ url: "/icon-512.png", sizes: "512x512", type: "image/png" },
		],
		shortcut: "/esai-mark.svg",
		apple: "/apple-touch-icon.png",
	},
	// canonical здесь НЕ задаём: корневой layout наследуют все страницы, и
	// canonical "/" на /privacy, /public-offer и прочих без своего canonical
	// говорил поисковику «это копия главной». Canonical главной — в (home)/page.tsx.
	openGraph: {
		title: "EsAI — Все нейросети в одном месте",
		description: SITE_DESCRIPTION,
		url: SITE_URL,
		siteName: SITE_NAME,
		type: "website",
		images: [OG_IMAGE_META],
	},
	twitter: {
		card: "summary_large_image",
		title: "EsAI — Все нейросети в одном месте",
		description: SITE_DESCRIPTION,
		images: [{ url: OG_IMAGE, alt: OG_IMAGE_ALT }],
	},
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
	const cookieStore = await cookies();
    const hdrs = await headers();

	const manual = cookieStore.get("NEXT_LOCALE_MANUAL")?.value === "1";
	const cookieLang = cookieStore.get("NEXT_LOCALE")?.value;
	// Язык интерфейса: ручной выбор залипает навсегда; иначе — по языку браузера
	// (Accept-Language: ky→kg, ru→ru, en→en, иначе русский). ТЗ клиента.
	const browserLang = localeFromAcceptLanguage(hdrs.get("accept-language"));
	const lang = (manual && cookieLang && ["ru", "en", "kg"].includes(cookieLang)) ? cookieLang : browserLang;

	const fpPk = process.env.NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY || process.env.FREEDOM_PAY_PUBLIC_KEY || "";
	// ВАЖНО: не впрыскиваем серверный секрет подписи в HTML. Только публичный SDK-токен (если задан).
	const fpToken = process.env.NEXT_PUBLIC_FREEDOM_PAY_TOKEN || "";
	const fpMerchantId = process.env.NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID || process.env.FREEDOM_PAY_MERCHANT_ID || "";

	const path = hdrs.get("x-esai-path");
	const authPath = (path || "").startsWith("/auth");
	// /save?f=/media/… — в адресе путь к личному файлу, открыть его может любой со ссылкой.
	// Метрика (webvisor, url:location.href) и gtag записали бы его в отчёты: здесь их нет.
	const analytics = path !== "/save";
	// Сервер рисует страницу целиком, с переводами, только на проверенных страницах
	// (i18n/settings.ts, SSR_ROUTES). I18N_SSR=off в окружении контейнера мгновенно,
	// без пересборки, возвращает старое поведение на всех страницах.
	const route = i18nSsrEnabled() ? routeI18n(path) : { ssr: false, ns: [] };
	const i18nData = route.ssr ? await loadI18nResources(lang as Language, route.ns) : null;
	// Подсказка «вошёл» для первого кадра (шапка, хаб) — см. components/bootstrap/AuthHint.
	const authedHint = hdrs.get("x-esai-authed") === "1";
	// На страницах с серверной отрисовкой настоящий H1 и текст уже в HTML: скрытый
	// SEO-блок там не нужен (иначе два H1, а у Академии — второй запрос каталога).
	const seoFallback = i18nData
		? null
		: path === "/" ? (
			<HomeSeoFallback lang={lang} />
		) : path === "/chat" ? (
			<ChatSeoFallback lang={lang} />
		) : path === "/academy" ? (
			<AcademySeoFallback lang={lang} search={hdrs.get("x-esai-search") || ""} />
		) : null;

	return (
		<html lang={lang === "kg" ? "ky" : lang} className="dark" data-theme="dark" suppressHydrationWarning>
			<head>
				<script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
				{/* Яндекс.Метрика (id 111652637, запрос клиента) и Google tag (AW-18298490299).
				    Заготовки ym/gtag и init/config ставятся сразу, в самом начале <head>:
				    время визита и очередь событий — как раньше. Сами tag.js и gtag.js
				    грузятся при первом действии посетителя (касание, клавиша, прокрутка)
				    или через 3 с после load: первый снимок Вебвизора был длинной задачей
				    2.5–3.9 с CPU прямо во время загрузки страницы (Lighthouse 22.11, ~96 %
				    блокировки на телефоне). На /auth/* — сразу: там колбэк конверсии. */}
				{analytics && (
					<script
						dangerouslySetInnerHTML={{
							__html: analyticsLoader(authPath),
						}}
					/>
				)}
				<script
					type="application/ld+json"
					dangerouslySetInnerHTML={{ __html: JSON.stringify(homeJsonLd()) }}
				/>
				{/* Google tag (gtag.js) — отслеживание конверсий Google Ads
				    (AW-18298490299, запрос клиента). На всех страницах через layout. */}
				{analytics && (
					<>
						{/* Event snippet «Регистрация»: функция вызывается в коде СТРОГО в
						    момент успешной регистрации (signin() при is_new и соц-колбэк при
						    welcome), а не по клику. Метка конверсии от клиента. */}
						<script
							dangerouslySetInnerHTML={{
								__html:
									"function gtag_report_conversion(url){var callback=function(){if(typeof(url)!='undefined'){window.location=url;}};gtag('event','conversion',{'send_to':'AW-18298490299/ZQw_CLDl98ocELubs5VE','event_callback':callback});return false;}",
							}}
						/>
					</>
				)}
			</head>
			<body>
				{/* Запасной пиксель Метрики для браузеров с отключённым JS. */}
				{analytics && (
					<noscript>
						<div>
							{/* eslint-disable-next-line @next/next/no-img-element */}
							<img src="https://mc.yandex.ru/watch/111652637" style={{ position: "absolute", left: "-9999px" }} alt="" />
						</div>
					</noscript>
				)}
				{/* Страховка от «сайта без стилей» после выкладки — см. lib/cssGuard. */}
				<script dangerouslySetInnerHTML={{ __html: CSS_GUARD }} />
				<DomainDefaults />
				<div id="alert-root"></div>
				<script
					id="fp-env"
					dangerouslySetInnerHTML={{
						__html: `window.__FP_ENV__=${JSON.stringify({ pk: fpPk, token: fpToken, merchantId: fpMerchantId })};`,
					}}
				/>
				{/* Страницы из SSR_ROUTES приходят с сервера целиком (словари — пропсом resources).
				    Остальные — по-старому: главная (при I18N_SSR=off), чат и Академия до загрузки
				    переводов отдают в HTML скрытый H1 и текст — для анализаторов ссылок и краулеров
				    без JS (путь и ?query передаёт middleware). */}
				<AuthHintProvider value={authedHint}>
					<I18nProvider
						lang={lang}
						fallback={seoFallback}
						resources={i18nData?.resources ?? null}
						ns={i18nData?.ns ?? []}
					>
						<BackToTopButton />
						{children}
						<EdgeThemeToggle />
						<PwaManager />
						<LowBalanceNotice />
						<PresencePing />
					</I18nProvider>
				</AuthHintProvider>
			</body>
		</html>
	);
}

// Загрузчик аналитики (см. комментарий в <head>). Строка, а не компонент: должна
// выполниться до гидратации, сразу при разборе <head>.
function analyticsLoader(immediate: boolean): string {
	return (
		"(function(w,d){" +
		"w.ym=w.ym||function(){(w.ym.a=w.ym.a||[]).push(arguments)};w.ym.l=1*new Date();" +
		"ym(111652637,'init',{ssr:true,webvisor:true,clickmap:true,ecommerce:'dataLayer',referrer:d.referrer,url:location.href,accurateTrackBounce:true,trackLinks:true});" +
		"w.dataLayer=w.dataLayer||[];w.gtag=w.gtag||function(){w.dataLayer.push(arguments)};gtag('js',new Date());gtag('config','AW-18298490299');" +
		"var done=0,ev=['pointerdown','keydown','touchstart','scroll'];" +
		"function add(s){var k=d.createElement('script');k.async=1;k.src=s;d.head.appendChild(k)}" +
		"function go(){if(done)return;done=1;ev.forEach(function(e){w.removeEventListener(e,go,true)});" +
		"add('https://mc.yandex.ru/metrika/tag.js?id=111652637');add('https://www.googletagmanager.com/gtag/js?id=AW-18298490299')}" +
		(immediate ? "go();" : "ev.forEach(function(e){w.addEventListener(e,go,{capture:true,passive:true})});" +
			"if(d.readyState==='complete')setTimeout(go,3000);else w.addEventListener('load',function(){setTimeout(go,3000)});") +
		"})(window,document);"
	);
}
