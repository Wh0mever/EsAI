import type { Metadata } from "next";
import Header from "@/components/main/Header";
import { SITE_NAME } from "@/lib/seo/site";

export const metadata: Metadata = {
	title: `Кейсы — ${SITE_NAME}`,
	description:
		"Примеры использования EsAI: как нейросети помогают в учёбе, работе и бизнесе.",
	robots: { index: false },
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		// Страница следует выбранной пользователем теме: цвета внутри — на токенах.
		<div className="min-h-[100dvh] bg-background text-foreground">
			<Header />
			{children}
		</div>
	);
}
