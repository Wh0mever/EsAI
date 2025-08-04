'use client';
import Header from "@/components/Header/Header";
import Footer from "@/components/Footer/Footer";
import { useTranslation } from "react-i18next";
import { useEffect } from "react";
import FreedomPayLoader from '@/components/UI/FreedomPayLoader';

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {

	const { t } = useTranslation('common');
	useEffect(() => {
		document.title = t('pages_titles.pricing');
	}, [t]);


	return (
		<>
			<FreedomPayLoader />
			<Header />
			{children}
			<Footer />
		</>
	);
}
