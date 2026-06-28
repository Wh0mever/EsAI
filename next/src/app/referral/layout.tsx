import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import { SITE_NAME, SITE_URL } from "@/lib/seo/site";

export const metadata: Metadata = {
	title: `Реферальная программа — ${SITE_NAME}`,
	description:
		"Реферальная программа EsAI: приглашайте друзей и получайте бонусы. Делитесь доступом ко всем нейросетям в одном месте.",
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
