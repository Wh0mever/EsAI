'use client';

import { useEffect, useState } from "react";
import Nav from "../Nav/HeaderNav";
import AuthButtons from "@/components/Auth/AuthButtons";

export default function Header() {
	const [scrolled, setScrolled] = useState(false);

	useEffect(() => {
		const handleScroll = () => {
			setScrolled(window.scrollY > 10);
		};

		window.addEventListener("scroll", handleScroll);
		return () => window.removeEventListener("scroll", handleScroll);
	}, []);

	return (
		<header
			className={`flex justify-between items-center fixed w-full select-none transition-all duration-300 z-200 gap-5 ${
				scrolled 
				? "py-4 bg-black/10 backdrop-blur" 
				: "py-15"
			} px-30`}
		>
			<div>
				<img src="/images/logo/base.svg" alt="" className="max-w-[150px]" />
			</div>

			<Nav />
			<AuthButtons />
		</header>
	);
}
