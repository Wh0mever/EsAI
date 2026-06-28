import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import FreedomPayLoader from "@/lib/freedompay/FreedomPayLoader";
import { SITE_NAME } from "@/lib/seo/site";

export const metadata: Metadata = {
	title: `Профиль — ${SITE_NAME}`,
	description: "Личный кабинет EsAI: тариф, токены, платежи и настройки аккаунта.",
	robots: { index: false },
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<>
			<FreedomPayLoader />
			<Header />
			{children}
			<Footer />
		</>
	);
}
