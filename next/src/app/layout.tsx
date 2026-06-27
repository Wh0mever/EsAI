import { cookies, headers } from "next/headers";
import { I18nProvider } from "@/i18n/i18n-provider";
import type { Metadata } from "next";
import BackToTopButton from "@/components/ui/toTop/BackToTop";
import "./globals.css";
import "highlight.js/styles/github-dark.css";
import "@/assets/style.scss";
import DomainDefaults from "@/components/bootstrap/DomainDefaults";
import { THEME_BOOTSTRAP } from "@/lib/theme";

export const metadata: Metadata = {
	title: "EsAI — Все AI в одном месте",
	description:
		"EsAI — нейросети в одном месте. ChatGPT, DeepSeek, Claude, Gemini онлайн на русском, кыргызском и английском. Пишите тексты, код, переводите и анализируйте документы.",
	keywords: [
		"EsAI",
		"нейросети",
		"ChatGPT",
		"DeepSeek",
		"Claude",
		"Gemini",
		"AI онлайн",
		"искусственный интеллект",
		"чат с нейросетью",
	],
	icons: {
		icon: "/esai-mark.svg",
		shortcut: "/esai-mark.svg",
		apple: "/esai-mark.svg",
	},
	openGraph: {
		title: "EsAI — Все AI в одном месте",
		description:
			"Все AI в одном месте. ChatGPT, DeepSeek, Claude, Gemini онлайн на русском и кыргызском.",
		siteName: "EsAI",
		type: "website",
		images: [{ url: "/esai-logo.svg" }],
	},
	twitter: {
		card: "summary_large_image",
		title: "EsAI — Все AI в одном месте",
		description: "Все AI в одном месте. ChatGPT, DeepSeek, Claude, Gemini онлайн.",
		images: ["/esai-logo.svg"],
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
  return "ru"; // fallback
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
	const fpToken = process.env.NEXT_PUBLIC_FREEDOM_PAY_TOKEN || process.env.FREEDOM_PAY_TOKEN || "";
	const fpMerchantId = process.env.NEXT_PUBLIC_FREEDOM_PAY_MERCHANT_ID || process.env.FREEDOM_PAY_MERCHANT_ID || "";

	return (
		<html lang={lang} className="dark" data-theme="dark" suppressHydrationWarning>
			<head>
				<script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
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
				<I18nProvider lang={lang}>{children}</I18nProvider>
			</body>
		</html>
	);
}
