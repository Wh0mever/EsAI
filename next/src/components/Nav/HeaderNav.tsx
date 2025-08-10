"use client";

import Link from "next/link";
import Cookies from "js-cookie";
import clsx from "clsx";
import { useTranslation } from "next-i18next";
import { DropDownHovered } from "@/components/UI/DropDown/DropDownHovered";
import { Button } from "@/components/UI/Buttons/Buttons";

type Variant = "desktop" | "mobile";

type Props = {
	variant?: Variant;
	className?: string;
	onNavigate?: () => void;
};

const languages = [
	{ code: "ru", icon: "/images/local/ru.webp", label: "Русский" },
	{ code: "en", icon: "/images/local/en.webp", label: "English" },
	{ code: "kg", icon: "/images/local/kg.webp", label: "Кыргызча" },
];

function MobileNav({ className, onNavigate, t, changeLanguage, currentLang }: any) {
	return (
		<nav className={clsx("text-white", className)}>
			<ul className="flex flex-col gap-2">
				<li>
					<Link href="/" onClick={onNavigate} className="block rounded-xl px-4 py-3 hover:bg-neutral-800">
						{t("nav.home")}
					</Link>
				</li>
				<li>
					<Link
						href="/pricing"
						onClick={onNavigate}
						className="block rounded-xl px-4 py-3 hover:bg-neutral-800"
					>
						{t("nav.pricing")}
					</Link>
				</li>
				<li>
					<Link href="/blog" onClick={onNavigate} className="block rounded-xl px-4 py-3 hover:bg-neutral-800">
						{t("nav.blog")}
					</Link>
				</li>
				<li className="mt-2">
					<div className="px-4 pb-1 text-xs uppercase tracking-wide text-neutral-400">
						{t("nav.categories")}
					</div>
					<div className="flex flex-col">
						<Link href="/about" onClick={onNavigate} className="block px-4 py-3 hover:bg-neutral-800">
							{t("nav.about")}
						</Link>
						<Link href="/contact-us" onClick={onNavigate} className="block px-4 py-3 hover:bg-neutral-800">
							{t("nav.contact")}
						</Link>
						<Link href="/faq" onClick={onNavigate} className="block px-4 py-3 hover:bg-neutral-800">
							{t("nav.help")}
						</Link>
						<Link
							href="/terms-conditions"
							onClick={onNavigate}
							className="block px-4 py-3 hover:bg-neutral-800"
						>
							{t("nav.terms")}
						</Link>
					</div>
				</li>
				<li className="mt-2">
					<div className="px-4 pb-1 text-xs uppercase tracking-wide text-neutral-400">
						{t("nav.currency")}
					</div>
					<div className="flex flex-col">
						<Link href="/" onClick={onNavigate} className="block px-4 py-3 hover:bg-neutral-800">
							$ USD
						</Link>
						<Link href="/" onClick={onNavigate} className="block px-4 py-3 hover:bg-neutral-800">
							₽ RUB
						</Link>
						<Link href="/" onClick={onNavigate} className="block px-4 py-3 hover:bg-neutral-800">
							с̲ KGS
						</Link>
					</div>
				</li>
				<li className="mt-2">
					<div className="px-4 pb-1 text-xs uppercase tracking-wide text-neutral-400">Language</div>
					<div className="flex flex-col">
						{languages.map(({ code, label, icon }) => (
							<button
								key={code}
								onClick={() => changeLanguage(code)}
								className={clsx(
									"flex items-center gap-2 text-left px-4 py-3 hover:bg-neutral-800 rounded-xl",
									currentLang === code && "bg-neutral-700"
								)}
							>
								<img src={icon} alt={label} className="h-4 w-6 object-cover rounded-[2px]" />
								<span>{label}</span>
							</button>
						))}
					</div>
				</li>
			</ul>
		</nav>
	);
}

function PCNav({ className, onNavigate, t, changeLanguage, currentLang }: any) {
	return (
		<nav className={clsx("bg-neutral-900 px-6 rounded-4xl flex items-center shadow-md", className)}>
			<ul className="flex items-center gap-10 text-md">
				<li className="py-3">
					<Link href="/" onClick={onNavigate}>
						{t("nav.home")}
					</Link>
				</li>

				<li className="py-3">
					<Link href="/pricing" onClick={onNavigate}>
						{t("nav.pricing")}
					</Link>
				</li>

				<li className="py-3">
					<Link href="/blog" onClick={onNavigate}>
						{t("nav.blog")}
					</Link>
				</li>

				<li className="py-3">
					<DropDownHovered
						handleText={<span className="flex items-center gap-1">{t("nav.categories")}</span>}
					>
						<ul className="flex flex-col text-sm py-2">
							<li className="border-b border-neutral-700">
								<Link
									href="/about"
									onClick={onNavigate}
									className="py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full"
								>
									{t("nav.about")}
								</Link>
							</li>
							<li className="border-b border-neutral-700">
								<Link
									href="/contact-us"
									onClick={onNavigate}
									className="py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full"
								>
									{t("nav.contact")}
								</Link>
							</li>
							<li className="border-b border-neutral-700">
								<Link
									href="/faq"
									onClick={onNavigate}
									className="py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full"
								>
									{t("nav.help")}
								</Link>
							</li>
							<li>
								<Link
									href="/terms-conditions"
									onClick={onNavigate}
									className="py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full"
								>
									{t("nav.terms")}
								</Link>
							</li>
						</ul>
					</DropDownHovered>
				</li>

				<li className="py-3">
					<DropDownHovered
						handleText={
							<span className="flex items-center gap-1">
								<img src={`/images/local/${currentLang}.webp`} alt="" />
							</span>
						}
					>
						<ul className="flex flex-col py-2 text-sm">
							{languages.map(({ code, icon, label }) => (
								<li key={code} className="border-b border-neutral-700">
									<Button
										onClick={() => changeLanguage(code)}
										className={clsx(
											"py-4 px-8 w-full text-left flex items-center gap-2 transition-all duration-300 hover:bg-neutral-800",
											currentLang === code && "bg-neutral-700"
										)}
									>
										<img
											src={icon}
											alt={label}
											className="min-w-4 h-4 w-6 object-cover rounded-[2px]"
										/>
										<span>{label}</span>
									</Button>
								</li>
							))}
						</ul>
					</DropDownHovered>
				</li>

				<li className="py-3 uppercase font-bold">
					<DropDownHovered handleText={<span className="flex items-center gap-1">с̲ KGS</span>}>
						<ul className="flex flex-col py-2 text-sm">
							<li className="border-b border-neutral-700">
								<Link
									href="/"
									onClick={onNavigate}
									className="py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full"
								>
									$ USD
								</Link>
							</li>
							<li className="border-b border-neutral-700">
								<Link
									href="/"
									onClick={onNavigate}
									className="py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full"
								>
									₽ RUB
								</Link>
							</li>
							<li>
								<Link
									href="/"
									onClick={onNavigate}
									className="py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full"
								>
									с̲ KGS
								</Link>
							</li>
						</ul>
					</DropDownHovered>
				</li>
			</ul>
		</nav>
	);
}

export default function Nav({ variant = "desktop", className, onNavigate }: Props) {
	const { t } = useTranslation("home");
	const currentLang = Cookies.get("NEXT_LOCALE") || "ru";

	const changeLanguage = (lang: string) => {
		Cookies.set("NEXT_LOCALE", lang);
		if (typeof window !== "undefined") window.location.reload();
	};

	if (variant === "mobile") {
		return (
			<MobileNav
				className={className}
				onNavigate={onNavigate}
				t={t}
				changeLanguage={changeLanguage}
				currentLang={currentLang}
			/>
		);
	} else {
		return (
			<PCNav
				className={className}
				onNavigate={onNavigate}
				t={t}
				changeLanguage={changeLanguage}
				currentLang={currentLang}
			/>
		);
	}
}
