"use client";
import { useTranslation } from "react-i18next";
import { useEffect } from "react";

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	const { t } = useTranslation("common");

	useEffect(() => {
		document.title = t("pages_titles.reset_password");
	}, [t]);

	return <>{children}</>;
}
