"use client";

import { useEffect } from "react";
import { Button } from "@/components/UI/Buttons/Buttons";

type ConfirmationModalProps = {
	isOpen: boolean;
	title: string;
	confirmText: string;
	cancelText: string;
	onConfirm: () => void;
	onCancel: () => void;
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
				<button className="absolute top-3 right-3 text-gray-500 hover:text-gray-800 cursor-pointer" onClick={onCancel}>
					&times;
				</button>
				<h2 className="text-md py-5 font-semibold mb-4">{title}</h2>
				<div className="flex justify-end gap-3">
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
