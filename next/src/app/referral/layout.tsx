import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import { SITE_NAME, SITE_URL } from "@/lib/seo/site";

export const metadata: Metadata = {
	title: `Партнёрство — ${SITE_NAME}`,
	description:
		"Партнёрская программа EsAI: приглашайте друзей и получайте кредиты с их пополнений — пожизненно.",
	alternates: { canonical: `${SITE_URL}/referral` },
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
