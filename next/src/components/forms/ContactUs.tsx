"use client";

import { Field, TextArea } from "@/components/ui/inputs/Inputs";
import { Button } from "@/components/ui/buttons/Buttons";
import { IoIosArrowRoundForward } from "react-icons/io";
import { useTranslation } from "react-i18next";
import SmartForm from "@/components/forms/SmartForm";
import { fetchData } from "@/tools/fetchData";
import { useState } from "react";
import { Alert } from "@/components/ui/alert/Alert";

export default function ContactUsForm() {
  const { t } = useTranslation("common");
  const [ok, setOk] = useState(false);

  return (
    <>
      <SmartForm
        className="flex flex-col gap-5 w-full"
        onSubmit={async (data: any) => {
          // map frontend->backend fields
          const payload = {
            name: data.name || "",
            email: data.email,
            tel: data.phone || "",
            question: data.message || "",
          };
          try {
            await fetchData("users/question/", "POST", payload, false);
            setOk(true);
          } catch {
            setOk(false);
          }
        }}
        submitLabel={t("contact_us.submit_button")}
      >
        <h2 className="text-2xl">{t("contact_us.form_title")}</h2>
        <p className="text-gray-400">{t("contact_us.form_subtitle")}</p>

        <Field
          name="name"
          label={t("contact_us.name_label")}
          placeholder={t("contact_us.name_placeholder")}
          className="w-full dark-field"
          required
        />

        <div className="flex gap-4 w-full">
          <Field
            name="email"
            type="email"
            label={t("contact_us.email_label")}
            placeholder={t("contact_us.email_placeholder")}
            className="flex-auto dark-field"
            required
          />
          <Field
            name="phone"
            type="tel"
            label={t("contact_us.phone_label")}
            placeholder={t("contact_us.phone_placeholder")}
            className="flex-auto dark-field"
          />
        </div>

        <TextArea
          name="message"
          label={t("contact_us.message_label")}
          className="w-full dark-field min-h-[100px]"
          required
        />

        <Button
          type="submit"
          className="w-fit px-5 py-3 mt-2 bg-indigo-500 flex gap-1 items-center rounded hover:bg-indigo-600 duration-300"
        >
          <span>{t("contact_us.submit_button")}</span>
          <i className="text-2xl">
            <IoIosArrowRoundForward />
          </i>
        </Button>
      </SmartForm>

      <Alert
        show={ok}
        onClose={() => setOk(false)}
        type="success"
        title={t("common.success")}
        message={t("faq.message_sended")}
        autoClose
        autoCloseDuration={3000}
        position="left"
        className="fixed left-4 bottom-4 z-[1000] max-h-fit"
      />
    </>
  );
}
