'use client';
import TextSlider from "@/components/UI/Sliders/TextSlider";
import { useTranslation } from "react-i18next";

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {

	const { t } = useTranslation('common');

	return (
		<main className="h-screen flex items-center justify-between bg-gray-800 relative">
			<div className="absolute top-0 left-0 w-full h-full z-0">
				<img src="/images/decorations/hero-bg-gradient.webp" alt="" className="w-full h-full object-cover" />
			</div>
			<div className="flex-auto flex flex-col gap-5 justify-center items-center p-10">
				<div className="text-center">
					<h2 className="text-5xl font-bold">{t('auth.your_music')}</h2>
					<h3
						className="text-5xl font-bold"
						style={{
							background: "linear-gradient(120deg, #9333ea, #EF4444)",
							backgroundClip: "text",
							WebkitBackgroundClip: "text",
							color: "transparent",
						}}
					>
						{t('auth.start_here')}
					</h3>
				</div>
				<TextSlider
					slides={[
						t('auth.welcome'),
						t('auth.create_music'),
						t('auth.create_pictures'),
						t('auth.gpt'),
						t('auth.you_can'),
					]}
					delay={3000}
				/>
			</div>
			<div className="bg-gray-200/70 h-full z-1 w-[400px] max-w-full">
				{children}
			</div>
		</main>
	);
}
