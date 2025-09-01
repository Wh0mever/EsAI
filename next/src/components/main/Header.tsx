"use client";

import { useEffect, useState } from "react";
import Nav from "./Nav";
import AuthButtons from "@/components/auth/AuthButtons";

export default function Header() {
	const [scrolled, setScrolled] = useState(false);
	const [open, setOpen] = useState(false);

	useEffect(() => {
		const handleScroll = () => setScrolled(window.scrollY > 10);
		window.addEventListener("scroll", handleScroll);
	}, []);

	useEffect(() => {
		if (open) document.body.classList.add("overflow-hidden");
		else document.body.classList.remove("overflow-hidden");
	}, [open]);

	const closeMenu = () => setOpen(false);

	return (
		<header
			className={`fixed w-full z-[200] bg-black/20 select-none transition-all duration-300
        ${scrolled ? "lg:py-2 py-2 bg-black/20 backdrop-blur" : "lg:py-2 py-2"}
        lg:px-20 px-10`}
		>
			<div className="flex items-center justify-between gap-5">
				<div className="flex items-center gap-4">
					<button
						className="lg:hidden cursor-pointer inline-flex h-12 w-12 items-center justify-center rounded-xl border border-neutral-800 bg-neutral-900/50 backdrop-blur active:scale-95"
						aria-label={open ? "Close menu" : "Open menu"}
						aria-expanded={open}
						onClick={() => setOpen((v) => !v)}
					>
						<span className="relative block h-5 w-6">
							<span
								className={`absolute left-0 top-0 h-0.5 w-6 bg-white transition-transform ${
									open ? "translate-y-2 rotate-45" : ""
								}`}
							/>
							<span
								className={`absolute left-0 top-2 h-0.5 w-6 bg-white transition-opacity ${
									open ? "opacity-0" : "opacity-100"
								}`}
							/>
							<span
								className={`absolute left-0 top-4 h-0.5 w-6 bg-white transition-transform ${
									open ? "-translate-y-2 -rotate-45" : ""
								}`}
							/>
						</span>
					</button>

					<img src="/images/logo/base.svg" alt="" className="max-w-[150px]" />
				</div>

				<div className="hidden lg:flex">
					<Nav variant="desktop" />
				</div>

				<AuthButtons />
			</div>

			<div
				className={`lg:hidden fixed inset-0 z-[190] transition-opacity ${
					open ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"
				}`}
				onClick={closeMenu}
			>
				<div className="absolute inset-0 bg-black/50" />
			</div>

			<aside
				className={`lg:hidden fixed right-0 top-0 z-[200] h-dvh w-[88%] max-w-[420px] bg-neutral-900/95 backdrop-blur-xl border-l border-neutral-800 transition-transform will-change-transform ${
					open ? "translate-x-0" : "translate-x-full"
				}`}
			>
				<div className="flex items-center justify-between p-6">
					<img src="/images/logo/base.svg" alt="" className="h-8" />
					<button
						className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-neutral-700 bg-neutral-800 active:scale-95 cursor-pointer"
						onClick={closeMenu}
						aria-label="Close"
					>
						<svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
							<path d="M6 6l12 12M18 6L6 18" />
						</svg>
					</button>
				</div>
				<div className="px-4 pb-8">
					<Nav variant="mobile" onNavigate={closeMenu} />
				</div>
			</aside>
		</header>
	);
}
