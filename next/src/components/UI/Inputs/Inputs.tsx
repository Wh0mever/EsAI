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

export function TextArea(FieldProps: FieldProps) {
	return (
		<div className="flex flex-col gap-2">
			<label htmlFor={FieldProps.id}>{FieldProps.label}</label>
			<textarea
				placeholder={FieldProps.placeholder}
				className={`rounded-lg px-3 py-2 border-1 border-gray-600 w-100 ${FieldProps.className}`}
				value={FieldProps.value}
				name={FieldProps.name}
				id={FieldProps.id}
				required={FieldProps.required}
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
	)

}

export function Checkbox(FieldProps: FieldProps) {
	return (
		<div className="flex gap-2 py-2">
			<label htmlFor={FieldProps.id}>{FieldProps.label}</label>
			<input
				type="checkbox"
				placeholder={FieldProps.placeholder}
				className={`rounded-lg p-2 border-1 border-gray-600 ${FieldProps.className}`}
				value={FieldProps.value}
				onChange={FieldProps.onChange}
				name={FieldProps.name}
				id={FieldProps.id}
				required={FieldProps.required}
			/>
		</div>
	);
}
