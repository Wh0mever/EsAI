"use client";

import { useEffect, useState } from "react";
import SmartForm from "@/components/forms/SmartForm";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { Field, TextArea } from "../ui/inputs/Inputs";

type Provider = { id: number; name: string };

export default function TemplatesCreationForm() {
	const { t } = useTranslation("common");
	const [providers, setProviders] = useState<Provider[]>([]);
	const [loadingProviders, setLoadingProviders] = useState(true);
	const [submitting, setSubmitting] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [ok, setOk] = useState(false);

	useEffect(() => {
		(async () => {
			try {
				const res = await fetchData("ai/providers/", "GET");
				if (res?.ok) setProviders(res.data as Provider[]);
			} finally {
				setLoadingProviders(false);
			}
		})();
	}, []);

	const onSubmit = async (data: Record<string, any>) => {
		setError(null);
		setOk(false);
		setSubmitting(true);

		const payload = {
			name: String(data.name || "").trim(),
			provider: Number(data.provider),
			template: String(data.template || ""),
			purpose: String(data.purpose || ""),
			description: String(data.description || ""),
			is_active: Boolean(data.is_active),
			is_public: Boolean(data.is_public),
		};

		if (!payload.name || !payload.provider || !payload.template || !payload.purpose) {
			setSubmitting(false);
			setError(t("forms.required_short"));
			return;
		}

		const res = await fetchData("ai/templates/", "POST", payload, true);
		setSubmitting(false);

		if (!res?.ok) {
			setError(t("templates.create.error"));
			return;
		}

		setOk(true);
		const form = document.querySelector<HTMLFormElement>("form[data-form='template-create']");
		form?.reset();
	};

    return (
        <SmartForm
            onSubmit={onSubmit}
            submitLabel={submitting ? t("templates.create.submitting") : t("templates.create.submit")}
            loadingLabel={t("templates.create.submitting")}
            className="w-full max-w-2xl mx-auto px-4 sm:px-6 md:px-8 space-y-4"
            data-form="template-create"
        >
            <Field
                label={t("templates.fields.name") + " *"}
                name="name"
                required
                placeholder={t("templates.placeholders.name")}
                className="w-full border border-neutral-600 py-3 px-4"
            />

            <Field
                label={t("templates.fields.purpose") + " *"}
                name="purpose"
                required
                placeholder={t("templates.placeholders.purpose")}
                className="w-full border border-neutral-600 py-3 px-4"
            />

			{/* provider (required) */}
            <label className="text-sm block">
                <span className="mb-1 block">{t("templates.fields.provider") + " *"}</span>
                <select
                    name="provider"
                    required
                    className="w-full bg-transparent border border-neutral-600 rounded-md py-3 px-4 outline-none"
					defaultValue=""
					disabled={loadingProviders}
				>
					<option value="" disabled className="bg-neutral-900">
						{loadingProviders ? t("common.loading") : t("templates.placeholders.provider")}
					</option>
					{providers.map((p) => (
						<option key={p.id} value={p.id} className="bg-neutral-900">
							{p.name}
						</option>
					))}
				</select>
			</label>

            <Field
                label={t("templates.fields.description")}
                name="description"
                placeholder={t("templates.placeholders.description")}
                className="w-full border border-neutral-600 py-3 px-4"
            />

            <TextArea
                label={t("templates.fields.template") + " *"}
                name="template"
                required
                placeholder={t("templates.placeholders.template")}
                className="w-full border border-neutral-600 py-3 px-4"
            />

			{error && <div className="text-red-400 text-sm">{error}</div>}
			{ok && <div className="text-green-400 text-sm">{t("templates.create.success")}</div>}
		</SmartForm>
	);
}
