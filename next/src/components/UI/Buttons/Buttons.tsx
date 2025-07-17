"use client";

import { useRouter } from "next/navigation";

interface ButtonProps {
	onClick?: () => void;
	children: React.ReactNode;
	disabled?: boolean;
	className?: string;
	type?: "button" | "submit" | "reset";
	style?: React.CSSProperties;
	description?: string;
	descriptionLeft?: boolean;
}

export function Button(ButtonProps: ButtonProps) {
	const { onClick, children, disabled, className, type, style } = ButtonProps;

	return (
		<button
			onClick={onClick ? onClick : () => {}}
			disabled={disabled}
			className={`cursor-pointer transition-all duration-300 ${className}`}
			type={type || "button"}
			style={style ? style : {}}
		>
			{children}
			{ButtonProps.description && (
				<span className={`btn-description ${ButtonProps.descriptionLeft && "btn-description"}`}>
					{ButtonProps.description}
				</span>
			)}
		</button>
	);
}

export function BackButton() {
	const router = useRouter();

	const handleBack = () => {
		if (window.history.length > 2) {
			router.back();
		} else {
			router.push("/");
		}
	};

	return <button onClick={handleBack}>← Назад</button>;
}
