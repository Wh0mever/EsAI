"use client";

import { useState, useRef, useEffect } from "react";
import { FaCheck } from "react-icons/fa";

interface FieldProps {
	type?: "text" | "password" | "email" | "number" | "tel" | "url";
	name: string;
	disabled?: boolean;
	placeholder?: string;
	className?: string;
	value?: string;
	id?: string;
	label?: string;
	required?: boolean;
	flexAuto?: boolean;
	onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

interface TextAreaProps extends Omit<FieldProps, "type"> {
	rows?: number;
	cols?: number;
}

interface CheckboxProps {
	name: string;
	disabled?: boolean;
	className?: string;
	checked?: boolean;
	id?: string;
	label?: string;
	required?: boolean;
	onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

export function Field(FieldProps: FieldProps) {
	return (
		<div className="flex flex-col gap-2 basis-auto flex-auto max-h-fit">
			{FieldProps.label && <label htmlFor={FieldProps.id}>{FieldProps.label}</label>}
			<input
				type={FieldProps.type || "text"}
				placeholder={FieldProps.placeholder}
				className={`rounded-md py-1 ${FieldProps.className}`}
				defaultValue={FieldProps.value}
				onChange={FieldProps.onChange}
				name={FieldProps.name}
				id={FieldProps.id}
				required={FieldProps.required}
				disabled={FieldProps.disabled || false}
			/>
		</div>
	);
}

export function TextArea(FieldProps: TextAreaProps) {
	return (
		<div className="flex flex-col gap-2">
			<label htmlFor={FieldProps.id}>{FieldProps.label}</label>
			<textarea
				placeholder={FieldProps.placeholder}
				className={`rounded-lg px-3 py-2 border-1 border-border-strong w-full ${FieldProps.className}`}
				value={FieldProps.value}
				name={FieldProps.name}
				id={FieldProps.id}
				required={FieldProps.required}
				disabled={FieldProps.disabled || false}
				rows={FieldProps.rows || 4}
				cols={FieldProps.cols || 50}
			/>
		</div>
	);
}

export function CardInput(FieldProps: FieldProps) {
	return (
		<div className="">
			<input type="number" className="px-3 py-2 border border-gray-500" />
			<input type="number" className="px-3 py-2 border border-gray-500" />
			<input type="number" className="px-3 py-2 border border-gray-500" />
			<input type="number" className="px-3 py-2 border border-gray-500" />
		</div>
	);
}

export function Checkbox(FieldProps: CheckboxProps) {
	const ref = useRef<HTMLInputElement>(null);
	const [checked, setChecked] = useState(FieldProps.checked);

	useEffect(() => {
		if (typeof FieldProps.checked === "boolean") {
			setChecked(FieldProps.checked);
			if (ref.current) {
				ref.current.checked = FieldProps.checked;
			}
		}
	}, [FieldProps.checked]);

	const toggleCheckbox = () => {
		if (ref.current) {
			const newValue = !ref.current.checked;
			ref.current.checked = newValue;
			setChecked(newValue);

			const event = {
				target: ref.current,
			};

			if (FieldProps?.onChange) {
				FieldProps.onChange(event as React.ChangeEvent<HTMLInputElement>);
			}
		}
	};

	return (
		<div className="flex gap-2 py-2 items-center">
			<input
				type="checkbox"
				className="hidden"
				name={FieldProps.name}
				id={FieldProps.id}
				required={FieldProps.required}
				ref={ref}
				onChange={(e: any) => FieldProps?.onChange(e)}
			/>
			<button type="button" className={`checkbox-view ${checked ? "active" : ""}`} onClick={toggleCheckbox}>
				<i>
					<FaCheck />
				</i>
			</button>
		</div>
	);
}
