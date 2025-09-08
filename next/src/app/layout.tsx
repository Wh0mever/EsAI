import { cookies } from "next/headers";
import { I18nProvider } from "@/i18n/i18n-provider";
import type { Metadata } from "next";
import BackToTopButton from "@/components/ui/toTop/BackToTop";
import "./globals.css";
import "@/assets/style.scss";

export const metadata: Metadata = {
	title: "Vokalo",
	keywords: ["nextjs", "tailwind", "dark mode"],
	icons: {
		icon: "/images/logo/head.ico",
		shortcut: "/images/logo/head.ico",
		apple: "/images/logo/head.svg",
	},
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
	const cookieStore = await cookies();
	const lang = cookieStore.get("NEXT_LOCALE")?.value || "ru";

	return (
		<html lang={lang} className="dark">
			<body>
				<BackToTopButton />
				<div id="alert-root"></div>
				<I18nProvider lang={lang}>{children}</I18nProvider>
			</body>
		</html>
	);
}
