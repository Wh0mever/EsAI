"use client";

import React, { useState } from "react";
import { Button } from "@/components/ui/buttons/Buttons";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/dialog/Dialog";
import SmartForm from "@/components/forms/SmartForm";
import { Field, TextArea } from "../ui/inputs/Inputs";

export default function Questions() {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation("common");

  return (
    <div className="flex flex-col gap-5 px-40 py-10 relative w-full h-fit">
      <img src="/images/decorations/pricing-faq-bottom-right.webp" className="absolute right-0 bottom-0" alt="" />
      <div className="flex flex-col gap-5 max-w-[500px]">
        <h3 className="text-4xl font-bold">{t("faq.title")} 👍</h3>
        <p className="text-gray-400">
          {t("faq.text")}{" "}
          <a href="mailto:support@esai.kg" className="text-indigo-400 hover:text-indigo-500 duration-300">
            support@esai.kg
          </a>
        </p>

        <Button
          onClick={() => setOpen(true)}
          className="rounded-3xl w-fit mt-5 bg-neutral-800 hover:bg-indigo-500 duration-300 px-4 py-3"
        >
          {t("faq.button")}
        </Button>
      </div>

      <Modal
        title={t("faq.modalTitle")}
        open={open}
        onClose={() => setOpen(false)}
        size="lg"
      >
        <SmartForm
		  onSubmit={async (data) => {
			setOpen(false);
		  }}
		  submitLabel={t("common.submit")}
		  loadingLabel={t("common.loading")}
		  className="w-full"
		>

		  <TextArea
			name="question"
			label={t("faq.questionDescription")}
			placeholder={t("faq.questionDescriptionPlaceholder")}
			required
			className="px-3 py-2 border border-neutral-300 rounded-md"
		  />
		</SmartForm>
      </Modal>
    </div>
  );
}
