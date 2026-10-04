import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import { SITE_NAME } from "@/lib/seo/site";

// Кабинет креатора — личный раздел: в поиск не отдаём (как профиль).
export const metadata: Metadata = {
	title: `Кабинет креатора — ${SITE_NAME}`,
	description: "Кабинет участника EsAI Creators: промокод и ссылка, статистика, публикации, комиссии и выплаты.",
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
