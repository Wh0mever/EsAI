// components/UserVisa.tsx
"use client";

import React, { useRef } from "react";
import { Card } from "@/components/ui/cards/Cards";
import { Button } from "@/components/ui/buttons/Buttons";
import { FaCcMastercard } from "react-icons/fa";
import { RiVisaLine } from "react-icons/ri";

type PropsVisa = {
  t: any;
  isCardLinked: boolean;
  cardData?: { brand: string; last4: string; expiry: string };
  onLinkCard?: () => void;       // optional: parent may use it after success
  onChangeCard?: () => void;
  onSubmitCard?: (card: {
    number: string;
    expMonth: string;
    expYear: string;
    cvv: string;
    holder: string;
  }) => Promise<void> | void;    // parent injects payment function
  threeDSContainerId?: string;   // default "fp-3ds" (parent renders container)
};

export default function UserVisa({
  t,
  isCardLinked,
  cardData,
  onLinkCard,
  onChangeCard,
  onSubmitCard,
  threeDSContainerId = "fp-3ds",
}: PropsVisa) {

  const VisaForm = () => {
    // number chunks
    const cardRefs = [
      useRef<HTMLInputElement>(null),
      useRef<HTMLInputElement>(null),
      useRef<HTMLInputElement>(null),
      useRef<HTMLInputElement>(null),
    ];
    // other fields
    const mmRef = useRef<HTMLInputElement>(null);
    const yyRef = useRef<HTMLInputElement>(null);
    const cvvRef = useRef<HTMLInputElement>(null);
    const holderRef = useRef<HTMLInputElement>(null);

    const handleCardInput = (e: React.ChangeEvent<HTMLInputElement>, index: number) => {
      const value = e.target.value.replace(/\D+/g, "").slice(0, 4);
      e.currentTarget.value = value;
      if (value.length === 4 && index < cardRefs.length - 1) {
        cardRefs[index + 1].current?.focus();
      }
    };

    const onSubmitLocal = async (e: React.FormEvent) => {
      e.preventDefault();
      const number =
        (cardRefs[0].current?.value || "") +
        (cardRefs[1].current?.value || "") +
        (cardRefs[2].current?.value || "") +
        (cardRefs[3].current?.value || "");

      const payload = {
        number: number.replace(/\D+/g, ""),
        expMonth: (mmRef.current?.value || "").replace(/\D+/g, ""),
        expYear: (yyRef.current?.value || "").replace(/\D+/g, ""),
        cvv: (cvvRef.current?.value || "").replace(/\D+/g, ""),
        holder: (holderRef.current?.value || "").trim(),
      };

      await onSubmitCard?.(payload);
    };

    return (
      <form onSubmit={onSubmitLocal} className="flex flex-col gap-5 justify-center items-start">
        <div className="flex flex-col w-full">
          <label className="text-gray-500">{t("profile.card_number")}</label>
          <div className="flex gap-2">
            {cardRefs.map((ref, i) => (
              <input
                className="border-b border-gray-500 p-2 text-center w-2/12 min-w-15"
                key={i}
                type="text"
                maxLength={4}
                inputMode="numeric"
                placeholder="****"
                pattern="\d*"
                ref={ref}
                onChange={(e) => handleCardInput(e, i)}
                required
              />
            ))}
          </div>
        </div>

        <div className="flex flex-col w-full">
          <label className="text-gray-500">{t("profile.expired_date")}</label>
          <div className="flex gap-2 items-center">
            <input
              ref={mmRef}
              type="text"
              placeholder="MM"
              maxLength={2}
              inputMode="numeric"
              pattern="\d*"
              required
              className="text-center px-3 py-2 border-b border-gray-500 w-2/12 min-w-15"
            />
            <span className="text-gray-500">/</span>
            <input
              ref={yyRef}
              type="text"
              placeholder="YY"
              maxLength={4}
              inputMode="numeric"
              pattern="\d*"
              required
              className="text-center px-3 py-2 border-b border-gray-500 w-2/12 min-w-15"
            />
          </div>
        </div>

        <div className="flex flex-col w-full">
          <label className="text-gray-500">CVV</label>
          <input
            ref={cvvRef}
            type="password"
            maxLength={4}
            inputMode="numeric"
            placeholder="***"
            pattern="\d*"
            required
            className="w-2/12 min-w-15 text-center px-3 py-2 border-b border-gray-500"
          />
        </div>

        <div className="flex flex-col w-full">
          <label className="text-gray-500">{t("profile.fullname")}</label>
          <input
            ref={holderRef}
            type="text"
            name="card_name"
            placeholder="John Doe"
            required
            className="w-3/12 px-3 py-2 border-b border-gray-500"
          />
        </div>

        {/* 3DS container renders OUTSIDE by parent; keep id here if хочешь внутри */}
        <div id={threeDSContainerId} className="hidden" />

        <Button type="submit" className="px-3 py-2 rounded-xl bg-indigo-500 hover:bg-indigo-700 mt-5">
          {t("profile.add_card")}
        </Button>
      </form>
    );
  };

  const VisaInfo = ({ cardData }: { cardData: any }) => {
    return (
      <>
        <p>
          <strong>{t("profile.brand")}:</strong> {cardData.brand}
        </p>
        <p>
          <strong>{t("profile.last4")}:</strong> **** **** **** {cardData.last4}
        </p>
        <p>
          <strong>{t("profile.period")}:</strong> {cardData.expiry}
        </p>
        <Button onClick={onChangeCard} className="px-6 py-2 rounded-xl bg-indigo-500 hover:bg-indigo-700 w-fit">
          {t("profile.change")}
        </Button>
      </>
    );
  };

  return (
    <Card>
      <div className="flex flex-col gap-3 w-full">
        <div className="flex justify-between items-center">
          <h2 className="text-xl font-bold">{t("profile.card")}</h2>
          <div className="flex gap-2">
            <i className="text-7xl text-gray-500">
              <RiVisaLine />
            </i>
            <i className="text-7xl text-gray-500">
              <FaCcMastercard />
            </i>
          </div>
        </div>
        {isCardLinked && cardData ? <VisaInfo cardData={cardData} /> : <VisaForm />}
      </div>
    </Card>
  );
}
