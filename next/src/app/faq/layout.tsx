"use client";
import Header from "@/components/Header/Header";
import Footer from "@/components/Footer/Footer";
import { useTranslation } from "next-i18next";
import { useEffect } from "react";

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {

	const { t } = useTranslation("common");
	useEffect(() => {
		document.title = t("pages_titles.faq");
	}, [t]);

	return (
		<>
			<Header />
			{children}
			<Footer />
		</>
	);
}
