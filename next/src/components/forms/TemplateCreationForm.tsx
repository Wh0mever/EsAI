'use client';

import { useEffect, useMemo, useState } from "react";
import SmartForm from "@/components/forms/SmartForm";
import { Button } from "@/components/ui/buttons/Buttons";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { Field, TextArea } from "../ui/inputs/Inputs";

type Provider = { id: number; name: string };

export default function TemplatesCreationForm() {
  const { t } = useTranslation("common");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  useEffect(() => {
    (async () => {
      const res = await fetchData("ai/providers/", "GET");
      if (res?.ok) setProviders(res.data as Provider[]);
    })();
  }, []);

  const onSubmit = async (data: Record<string, any>) => {
    setError(null);
    setOk(false);
    setSubmitting(true);

    // normalize payload
    const payload = {
      name: String(data.name || "").trim(),
      provider: Number(data.provider),
      template: String(data.template || ""),
      purpose: String(data.purpose || ""),
      description: String(data.description || ""),
      is_active: Boolean(data.is_active),
      is_public: Boolean(data.is_public),
    };

    // quick client-side checks
    if (!payload.name || !payload.provider || !payload.template || !payload.purpose) {
      setSubmitting(false);
      setError("Заполни обязательные поля");
      return;
    }

    const res = await fetchData("ai/templates/", "POST", payload, true);
    setSubmitting(false);

    if (!res?.ok) {
      setError("Не удалось создать шаблон");
      return;
    }

    setOk(true);
    // reset form
    const form = document.querySelector<HTMLFormElement>("form[data-form='template-create']");
    form?.reset();
  };

  return (
    <SmartForm
      onSubmit={onSubmit}
      submitLabel={submitting ? "Создание..." : "Создать шаблон"}
      loadingLabel="Создание..."
      className="max-w-2xl"
    >
      <form data-form="template-create" className="contents">
        <Field
          label="Название *"
          name="name"
          required
          placeholder="Напр.: Политый системный промпт для Vokalo"
          className="border border-neutral-600 py-3 px-4"
        />


        <Field
          label="Назначение *"
          name="purpose"
          required
          placeholder="Кратко: для чего этот шаблон"
          className="border border-neutral-600 py-3 px-4"
        />

        <Field
          label="Описание"
          name="description"
          placeholder="Опционально: как использовать, ограничения..."
          className="border border-neutral-600 py-3 px-4"
        />

        <TextArea
          label="Тело шаблона *"
          name="template"
          required
          placeholder="Подставляй {{variables}} или {{language}}, если у тебя есть собственный рендерер"
          className="border border-neutral-600 py-3 px-4"
        />

        {error && <div className="text-red-400 text-sm">{error}</div>}
        {ok && <div className="text-green-400 text-sm">Шаблон создан</div>}
      </form>
    </SmartForm>
  );
}
