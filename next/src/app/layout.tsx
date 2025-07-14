import { cookies } from "next/headers";
import { I18nProvider } from "@/i18n/i18n-provider";
import "./globals.css";
import "@/assets/style.scss";

export default async function RootLayout({ children }: { children: React.ReactNode }) {
	const cookieStore = await cookies();
	const lang = cookieStore.get("NEXT_LOCALE")?.value || "ru";

	return (
		<html lang={lang}>
			<body>
				<I18nProvider lang={lang}>
					{children}
				</I18nProvider>
			</body>
		</html>
	);
}
