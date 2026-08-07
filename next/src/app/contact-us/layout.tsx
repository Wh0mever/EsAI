import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import { SITE_NAME, SITE_URL } from "@/lib/seo/site";

export const metadata: Metadata = {
	title: `Контакты — ${SITE_NAME}`,
	description:
		"Свяжитесь с EsAI: поддержка, вопросы по оплате и тарифам, сотрудничество. Напишите нам на почту или в Telegram — отвечаем в рабочие дни.",
	alternates: { canonical: `${SITE_URL}/contact-us` },
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		// Страница следует выбранной пользователем теме: цвета берём из токенов,
		// поэтому текст и карточки читаются и в светлой, и в тёмной теме.
		<div className="min-h-[100dvh] bg-background text-foreground">
			<Header />
			{children}
			<Footer />
		</div>
	);
}
