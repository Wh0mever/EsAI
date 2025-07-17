"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";
import Cookies from "js-cookie";
import { useEffect, useState } from "react";

export default function AuthButtons() {
	const { t } = useTranslation("home");
	const [isAuthenticated, setIsAuthenticated] = useState(false);

	useEffect(() => {
		const checkAuth = () => {
			const token = Cookies.get("access");
			setIsAuthenticated(!!token);
		};

		checkAuth();
	}, []);

	if (isAuthenticated) {
		return (
			<div className="bg-neutral-900 px-3 rounded-4xl flex justify-center items-center py-2 gap-2 shadow-md">
				<Link href="/dashboard" className="bg-indigo-500 px-4 py-2 rounded-3xl hover:bg-indigo-600 text-nowrap">
					{t("nav.dashboard")}
				</Link>
			</div>
		);
	}

	return (
		<div className="bg-neutral-900 px-3 rounded-4xl flex justify-center items-center py-2 gap-2 shadow-md">
			<Link
				href="/auth/signin"
				className="bg-neutral-900 border-1 border-neutral-700 px-4 py-2 rounded-3xl hover:bg-indigo-600 hover:border-neutral-900"
			>
				{t("nav.signin")}
			</Link>
			<div className="text-neutral-700 px-1 h-full">|</div>
			<Link href="/auth/signup" className="bg-indigo-500 px-4 py-2 rounded-3xl hover:bg-indigo-600">
				{t("nav.signup")}
			</Link>
		</div>
	);
}
