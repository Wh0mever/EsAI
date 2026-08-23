import { cookies, headers } from "next/headers";
import { I18nProvider } from "@/i18n/i18n-provider";
import type { Metadata, Viewport } from "next";
import BackToTopButton from "@/components/ui/toTop/BackToTop";
import PwaManager from "@/components/pwa/PwaManager";
import "./globals.css";
import "highlight.js/styles/github-dark.css";
import "@/assets/style.scss";
import DomainDefaults from "@/components/bootstrap/DomainDefaults";
import { THEME_BOOTSTRAP } from "@/lib/theme";
import { CSS_GUARD } from "@/lib/cssGuard";
import { SITE_URL, SITE_NAME, OG_IMAGE } from "@/lib/seo/site";
import { homeJsonLd } from "@/lib/seo/jsonLd";
import { localeFromAcceptLanguage } from "@/lib/localeDetect";

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
	description:
		"EsAI — нейросети в одном месте. ChatGPT, DeepSeek, Claude, Gemini онлайн на русском, кыргызском и английском. Пишите тексты, код, переводите и анализируйте документы.",
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
	alternates: {
		canonical: "/",
	},
	openGraph: {
		title: "EsAI — Все нейросети в одном месте",
		description:
			"EsAI — Все нейросети в одном месте. Без лишних трат и подписок.",
		url: SITE_URL,
		siteName: SITE_NAME,
		type: "website",
		images: [{ url: OG_IMAGE }],
	},
	twitter: {
		card: "summary_large_image",
		title: "EsAI — Все нейросети в одном месте",
		description: "EsAI — Все нейросети в одном месте. Без лишних трат и подписок.",
		images: [OG_IMAGE],
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

	return (
		<html lang={lang === "kg" ? "ky" : lang} className="dark" data-theme="dark" suppressHydrationWarning>
			<head>
				<script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
				{/* Яндекс.Метрика (id 111652637, запрос клиента). Стоит максимально
				    рано в <head>, сразу после бутстрапа темы: просмотр засчитается,
				    даже если посетитель почти сразу закроет страницу. Сам tag.js
				    грузится асинхронно и рендер не задерживает. */}
				<script
					dangerouslySetInnerHTML={{
						__html:
							"(function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};m[i].l=1*new Date();for(var j=0;j<document.scripts.length;j++){if(document.scripts[j].src===r){return;}}k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)})(window,document,'script','https://mc.yandex.ru/metrika/tag.js?id=111652637','ym');ym(111652637,'init',{ssr:true,webvisor:true,clickmap:true,ecommerce:\"dataLayer\",referrer:document.referrer,url:location.href,accurateTrackBounce:true,trackLinks:true});",
					}}
				/>
				<script
					type="application/ld+json"
					dangerouslySetInnerHTML={{ __html: JSON.stringify(homeJsonLd()) }}
				/>
				{/* Google tag (gtag.js) — отслеживание конверсий Google Ads
				    (AW-18298490299, запрос клиента). На всех страницах через layout. */}
				<script async src="https://www.googletagmanager.com/gtag/js?id=AW-18298490299" />
				<script
					dangerouslySetInnerHTML={{
						__html:
							"window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','AW-18298490299');",
					}}
				/>
				{/* Event snippet «Регистрация»: функция вызывается в коде СТРОГО в
				    момент успешной регистрации (signin() при is_new и соц-колбэк при
				    welcome), а не по клику. Метка конверсии от клиента. */}
				<script
					dangerouslySetInnerHTML={{
						__html:
							"function gtag_report_conversion(url){var callback=function(){if(typeof(url)!='undefined'){window.location=url;}};gtag('event','conversion',{'send_to':'AW-18298490299/ZQw_CLDl98ocELubs5VE','event_callback':callback});return false;}",
					}}
				/>
			</head>
			<body>
				{/* Запасной пиксель Метрики для браузеров с отключённым JS. */}
				<noscript>
					<div>
						{/* eslint-disable-next-line @next/next/no-img-element */}
						<img src="https://mc.yandex.ru/watch/111652637" style={{ position: "absolute", left: "-9999px" }} alt="" />
					</div>
				</noscript>
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
				<I18nProvider lang={lang}>
					<BackToTopButton />
					{children}
					<PwaManager />
				</I18nProvider>
			</body>
		</html>
	);
}
