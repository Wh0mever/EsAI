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
import { SITE_URL, SITE_NAME, OG_IMAGE } from "@/lib/seo/site";
import { homeJsonLd } from "@/lib/seo/jsonLd";

export const viewport: Viewport = {
	width: "device-width",
	initialScale: 1,
	viewportFit: "cover",
	themeColor: [
		{ media: "(prefers-color-scheme: dark)", color: "#141414" },
		{ media: "(prefers-color-scheme: light)", color: "#F5C518" },
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
		"Mistral",
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

function normalizeHost(input: string) {
  const first = (input || "").split(",")[0].trim().toLowerCase();
  return first.split(":")[0];
}

function localeByHost(host: string) {
  const h = normalizeHost(host);
  if (h.endsWith(".ru")) return "ru";
  if (h.endsWith(".kg")) return "kg";
  if (h.endsWith(".online") || h.endsWith(".com")) return "en";
  return "kg"; // fallback — kg by default (ТЗ)
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
	const cookieStore = await cookies();
    const hdrs = await headers();
    const host = normalizeHost(hdrs.get("x-forwarded-host") || hdrs.get("host") || "");

	const manual = cookieStore.get("NEXT_LOCALE_MANUAL")?.value === "1";
	const cookieLang = cookieStore.get("NEXT_LOCALE")?.value;
	const computed = localeByHost(host);
	const lang = manual && cookieLang ? cookieLang : (cookieLang && ["ru","en","kg"].includes(cookieLang) ? cookieLang : computed);

	const fpPk = process.env.NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY || process.env.FREEDOM_PAY_PUBLIC_KEY || "";
	// ВАЖНО: не впрыскиваем серверный секрет подписи в HTML. Только публичный SDK-токен (если задан).
	const fpToken = process.env.NEXT_PUBLIC_FREEDOM_PAY_TOKEN || "";
	const fpMerchantId = process.env.NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID || process.env.FREEDOM_PAY_MERCHANT_ID || "";

	return (
		<html lang={lang} className="dark" data-theme="dark" suppressHydrationWarning>
			<head>
				<script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
				<script
					type="application/ld+json"
					dangerouslySetInnerHTML={{ __html: JSON.stringify(homeJsonLd()) }}
				/>
			</head>
			<body>
				<DomainDefaults />
				<BackToTopButton />
				<div id="alert-root"></div>
				<script
					id="fp-env"
					dangerouslySetInnerHTML={{
						__html: `window.__FP_ENV__=${JSON.stringify({ pk: fpPk, token: fpToken, merchantId: fpMerchantId })};`,
					}}
				/>
				<I18nProvider lang={lang}>
					{children}
					<PwaManager />
				</I18nProvider>
			</body>
		</html>
	);
}
