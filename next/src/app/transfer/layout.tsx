import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import { SITE_NAME } from "@/lib/seo/site";

export const metadata: Metadata = {
	title: `Перевести кредиты — ${SITE_NAME}`,
	description: "Переводите кредиты другим пользователям EsAI и смотрите историю переводов.",
	robots: { index: false },
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<>
			<Header />
			{children}
			<Footer />
		</>
	);
}
