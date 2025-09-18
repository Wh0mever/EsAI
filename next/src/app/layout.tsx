import { cookies, headers } from "next/headers";
import { I18nProvider } from "@/i18n/i18n-provider";
import type { Metadata } from "next";
import BackToTopButton from "@/components/ui/toTop/BackToTop";
import "./globals.css";
import "@/assets/style.scss";
import DomainDefaults from "@/components/bootstrap/DomainDefaults";

export const metadata: Metadata = {
	title: "Vokalo",
	keywords: ["nextjs", "tailwind", "dark mode"],
	icons: {
		icon: "/images/logo/head.ico",
		shortcut: "/images/logo/head.ico",
		apple: "/images/logo/head.svg",
	},
};

function localeByHost(host: string) {
  const h = (host || "").toLowerCase();
  if (h.endsWith("vokalo.ru")) return "ru";
  if (h.endsWith("vokalo.kg")) return "kg";
  if (h.endsWith("vokalo.online")) return "en";
  return "ru"; // fallback
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
	const cookieStore = await cookies();
	const hdrs = await headers();
	const host = hdrs.get("host") || "";

	const manual = cookieStore.get("NEXT_LOCALE_MANUAL")?.value === "1";
	const cookieLang = cookieStore.get("NEXT_LOCALE")?.value;
	const computed = localeByHost(host);
	const lang = manual && cookieLang ? cookieLang : (cookieLang && ["ru","en","kg"].includes(cookieLang) ? cookieLang : computed);

	return (
		<html lang={lang} className="dark">
			<body>
				<DomainDefaults />
				<BackToTopButton />
				<div id="alert-root"></div>
				<I18nProvider lang={lang}>{children}</I18nProvider>
			</body>
		</html>
	);
}
