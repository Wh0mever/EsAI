import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import { SITE_NAME, SITE_URL } from "@/lib/seo/site";

export const metadata: Metadata = {
	title: `Условия и положения — ${SITE_NAME}`,
	description:
		"Условия использования сервиса EsAI: правила доступа к нейросетям, оплата, ответственность сторон и порядок работы платформы.",
	alternates: { canonical: `${SITE_URL}/terms-conditions` },
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
