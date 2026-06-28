"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Отдельной регистрации больше нет: единая авторизация «Войти» на /auth/signin
 * (при первом входе аккаунт создаётся автоматически).
 * Эта страница — простой редирект на /auth/signin.
 */
export default function SignUp() {
	const router = useRouter();

	useEffect(() => {
		router.replace("/auth/signin");
	}, [router]);

	return null;
}
