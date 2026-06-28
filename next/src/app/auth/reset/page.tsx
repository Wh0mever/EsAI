"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Пароля больше нет (вход по email-OTP без пароля), поэтому сброс пароля неактуален.
 * Эта страница — простой редирект на единый экран входа /auth/signin.
 */
export default function ResetPassword() {
	const router = useRouter();

	useEffect(() => {
		router.replace("/auth/signin");
	}, [router]);

	return null;
}
