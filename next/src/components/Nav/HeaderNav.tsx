import { DropDownHovered } from "@/components/UI/DropDown/DropDownHovered";
import { useTranslation } from "next-i18next";
import { Button } from "@/components/UI/Buttons/Buttons";
import Link from "next/link";
import Cookies from "js-cookie";

const languages = [
	{ code: "ru", icon: "/images/local/ru.webp" },
	{ code: "en", icon: "/images/local/en.webp" },
	{ code: "kg", icon: "/images/local/kg.webp" },
];

export default function Nav() {
	const { t } = useTranslation("home");
	const currentLang = Cookies.get("NEXT_LOCALE") || "ru";
	const changeLanguage = (lang: string) => {
		Cookies.set("NEXT_LOCALE", lang);
		window.location.reload();
	};
	return (
		<nav className="bg-neutral-900 px-6 rounded-4xl flex justify-center items-center shadow-md">
			<ul className="flex gap-10 text-md">
				<li className="block py-3">
					<Link href={"/"}>{t("nav.home")}</Link>
				</li>
				<li className="block py-3">
					<Link href={"/pricing"}>{t("nav.pricing")}</Link>
				</li>
				<li className="block py-3">
					<Link href={"/blog"}>{t("nav.blog")}</Link>
				</li>

				<li className="block py-3">
					<DropDownHovered handleText={<span className="flex items-center gap-1">{t("nav.categories")}</span>}>
						<ul className="flex flex-col flex-grow py-2 text-sm">
							<li className="border-b border-neutral-700 flex-grow">
								<Link
									href={"/about"}
									className="py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full"
								>
									{t("nav.about")}
								</Link>
							</li>
							<li className="border-b border-neutral-700 flex-grow">
								<Link
									href={"/contact-us"}
									className="py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full"
								>
									{t("nav.contact")}
								</Link>
							</li>
							<li className="border-b border-neutral-700 flex-grow">
								<Link
									href={"/faq"}
									className="py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full"
								>
									{t("nav.help")}
								</Link>
							</li>
							<li className="flex-grow">
								<Link
									href={"/terms-conditions"}
									className="py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full"
								>
									{t("nav.terms")}
								</Link>
							</li>
						</ul>
					</DropDownHovered>
				</li>

				<li className="block py-3">
					<DropDownHovered
						handleText={
							<span className="flex items-center gap-1">
								<img src={`/images/local/${currentLang}.webp`} alt="" />
							</span>
						}
					>
						<ul className="flex flex-col py-2 text-sm">
							{languages.map(({ code, icon }) => (
								<li key={code} className="border-b border-neutral-700">
									<Button
										onClick={() => changeLanguage(code)}
										className={`py-4 px-8 w-full text-left flex items-center gap-2 transition-all duration-300 hover:bg-neutral-800 ${
											currentLang === code ? "bg-neutral-700" : ""
										}`}
									>
										<img src={icon} alt={code.toUpperCase()} className="min-w-4" />
									</Button>
								</li>
							))}
						</ul>
					</DropDownHovered>
				</li>

				<li className="block py-3 uppercase bold font-bold">
					<DropDownHovered handleText={<span className="flex items-center gap-1">с̲ KGS</span>}>
						<ul className="flex flex-col flex-grow py-2 text-sm">
							<li className="border-b border-neutral-700 flex-grow">
								<Link
									href={"/"}
									className="py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full"
								>
									$ usd
								</Link>
							</li>
							<li className="border-b border-neutral-700 flex-grow">
								<Link
									href={"/"}
									className="py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full"
								>
									₽ RUB
								</Link>
							</li>
							<li className="border-b border-neutral-700 flex-grow">
								<Link
									href={"/"}
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
