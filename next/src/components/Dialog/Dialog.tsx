"use client";

import { ReactNode, useEffect } from "react";
import { createPortal } from "react-dom";
import { IoClose } from "react-icons/io5";
import { Button } from "@/components/UI/Buttons/Buttons";

type ConfirmationModalProps = {
	isOpen: boolean;
	title: string;
	confirmText: string;
	cancelText: string;
	onConfirm: () => void;
	onCancel: () => void;
};

type ModalProps = {
	title: string;
	children: ReactNode;
	size?: "full" | "lg" | "md" | "sm";
	onClose: () => void;
	open: boolean;
};

const sizeClasses = {
	sm: "max-w-sm rounded-2xl shadow-lg",
	md: "max-w-md rounded-2xl shadow-lg",
	lg: "max-w-4xl rounded-2xl shadow-lg",
	full: "w-full h-full rounded-none shadow-none",
};

export function ConfirmationModal({
	isOpen,
	title,
	confirmText,
	cancelText,
	onConfirm,
	onCancel,
}: ConfirmationModalProps) {
	useEffect(() => {
		const handleEsc = (e: KeyboardEvent) => {
			if (e.key === "Escape") onCancel();
		};
		document.addEventListener("keydown", handleEsc);
		return () => document.removeEventListener("keydown", handleEsc);
	}, [onCancel]);

	if (!isOpen) return null;

	return (
		<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
			<div className="bg-neutral-900 rounded-lg shadow-lg w-full max-w-md p-6 relative">
				<h2 className="text-xl font-semibold mb-4 border-b py-2 border-neutral-600">{title}</h2>
				<button
					className="text-gray-500 text-lg absolute right-5 top-5 hover:text-gray-800 cursor-pointer"
					onClick={onCancel}
				>
					<IoClose />
				</button>
				<div className="flex justify-end gap-3 mt-3">
					<Button
						className="px-4 py-2 text-sm bg-rose-700 text-white rounded hover:bg-rose-800"
						onClick={onConfirm}
					>
						{confirmText}
					</Button>
					<Button className="px-4 py-2 text-sm bg-gray-500 rounded hover:bg-gray-400" onClick={onCancel}>
						{cancelText}
					</Button>
				</div>
			</div>
		</div>
	);
}

export function Modal({ title, children, size = "md", onClose, open }: ModalProps) {
	useEffect(() => {
		document.body.style.overflow = "hidden";
		return () => {
			document.body.style.overflow = "";
		};
	}, []);

	return createPortal(
		<div className={`fixed inset-0 z-50 items-center justify-center bg-black/50 ${open ? "flex" : "hidden"}`}>
			<div
				className={`bg-white dark:bg-neutral-900 w-full p-5 ${sizeClasses[size]} ${
					size === "full" ? "" : "mx-4"
				} p-6 relative`}
			>
				<h2 className="text-xl font-semibold mb-4 border-b py-2 border-neutral-600">{title}</h2>
				<button
					onClick={onClose}
					className="absolute top-5 text-xl right-5 text-gray-400 hover:text-gray-600 transition"
				>
					<IoClose />
				</button>
				<div className="mt-3">{children}</div>
			</div>
		</div>,
		document.body
	);
}
