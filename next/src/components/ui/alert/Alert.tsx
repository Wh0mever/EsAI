import React, { useEffect } from "react";
import "./Alert.scss"; //
import { IoClose } from "react-icons/io5";
import { CgDanger } from "react-icons/cg";
import { IoIosCheckmarkCircleOutline } from "react-icons/io";

interface AlertProps {
	title?: string;
	message?: string;
	type?: "success" | "error" | "info" | "warning";
	onClose?: () => void;
	className?: string;
	show?: boolean;
	duration?: number;
	closeButton?: boolean;
	position?: "top" | "bottom" | "left" | "right";
	autoClose?: boolean;
	autoCloseDuration?: number;
}

export function Alert({
	title = "Alert",
	message = "This is an alert message.",
	type = "info",
	onClose,
	className = "",
	show = true,
	closeButton = true,
	position = "top",
	autoClose = true,
	autoCloseDuration = 3000,
}: AlertProps) {
	useEffect(() => {
		if (autoClose && show && onClose) {
			const timer = setTimeout(() => {
				onClose();
			}, autoCloseDuration);

			return () => clearTimeout(timer);
		}
	}, [autoClose, autoCloseDuration, onClose, show]);

	if (!show) return null;

	const alertClasses = `alert alert-${type} ${className} alert-position-${position}`;

	return (
		<div className={alertClasses}>
			<div className="alert-content pe-5 flex flex-col gap-1">
				<div className="flex justify-between items-center gap-3">
					<h5 className="text-lg font-bold flex items-center gap-2">
						{type === "error" && <CgDanger className="text-2xl text-red-500" />}
						{type === "success" && <IoIosCheckmarkCircleOutline className="text-2xl text-green-500" />}
						{type === "info" && <IoIosCheckmarkCircleOutline className="text-2xl text-blue-500" />}
						{title}
					</h5>
					{closeButton && (
						<button className="alert-close text-xl font-bold" onClick={onClose}>
							<IoClose />
						</button>
					)}
				</div>
				<p>{message}</p>
			</div>
		</div>
	);
}
