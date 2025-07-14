import React, { useState } from "react";
import { Field, Checkbox } from "@/components/UI/Inputs/Inputs";
import { Button } from "@/components/UI/Buttons/Buttons";

export default function AppForm({ fieldsConfig }: { fieldsConfig: any }) {
	const [formData, setFormData] = useState<any>({});
	const [loading, setLoading] = useState(false);

	return (
		<form className="">

            {/* container */}
            <div className="grid grid-col-1 lg:grid-cols-2 gap-4">
            {fieldsConfig &&
				Object.keys(fieldsConfig).map((key) => {
					const field = fieldsConfig[key];
					return (
						<div key={key} className="flex flex-col gap-2 min-w-0">
							{field.type === "BooleanField" ? (
								<Checkbox
									id={key}
									label={field.label}
									name={key}
									value={formData[key]}
									onChange={(e) => setFormData({ ...formData, [key]: e.target.checked })}
								/>
							) : (
								<Field
									id={key}
									label={field.label}
									type={field.type}
									placeholder={field.placeholder}
									name={key}
									value={formData[key]}
									onChange={(e) => setFormData({ ...formData, [key]: e.target.value })}
								/>
							)}
						</div>
					);
				})}

            </div>

            {/* actions */}
			<div className="py-4 flex gap-4">
				<Button
					onClick={() => {}}
					className="bg-green-700 text-white px-4 py-2 rounded-lg"
					type="submit"
					disabled={loading}
				>
					Сохранить
				</Button>
				<Button
					onClick={() => {}}
					className="bg-gray-700 text-white px-4 py-2 rounded-lg"
					type="submit"
					disabled={loading}
				>
					Вернуться
				</Button>

			</div>
		</form>
	);
}
