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
		// Тёмная по дизайну страница с маркетинговой шапкой: фиксируем тёмные
		// токены, чтобы в светлой теме шапка/логотип не пропадали на белом.
		<div data-theme="dark" className="min-h-[100dvh] bg-background text-foreground">
			<Header />
			{children}
		</div>
	);
}
