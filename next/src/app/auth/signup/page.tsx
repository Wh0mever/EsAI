"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Cookies from "js-cookie";

/**
 * Отдельной регистрации больше нет: единая авторизация «Войти» на /auth/signin
 * (при первом входе аккаунт создаётся автоматически).
 * Эта страница — редирект на /auth/signin. Реферальный код из ?ref сохраняем в
 * cookie esai_ref (30 дней), чтобы бэк начислил бонус пригласившему при создании
 * аккаунта (cookie уходит на тот же origin /api и для email-, и для соц-входа).
 */
export default function SignUp() {
	const router = useRouter();

	useEffect(() => {
		try {
			const ref = new URLSearchParams(window.location.search).get("ref");
			if (ref) Cookies.set("esai_ref", ref, { expires: 30, sameSite: "lax" });
		} catch {}
		router.replace("/auth/signin");
	}, [router]);

	return null;
}
