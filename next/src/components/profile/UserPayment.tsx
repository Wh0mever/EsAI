"use client";

import React, { useEffect, useState, useRef } from "react";
import { Card } from "@/components/ui/cards/Cards";
import { Button } from "@/components/ui/buttons/Buttons";
import { FaCcMastercard } from "react-icons/fa";
import { RiVisaLine } from "react-icons/ri";

type PropsVisa = {
	t: any;
	isCardLinked: boolean;
	cardData?: {
		brand: string;
		last4: string;
		expiry: string;
	};
	onLinkCard?: () => void;
	onChangeCard?: () => void;
};

export default function UserVisa({ t, isCardLinked, cardData, onLinkCard, onChangeCard }: PropsVisa) {
	const VisaForm = () => {
		const cardRefs = [
			useRef<HTMLInputElement>(null),
			useRef<HTMLInputElement>(null),
			useRef<HTMLInputElement>(null),
			useRef<HTMLInputElement>(null),
		];

		const handleCardInput = (e: React.ChangeEvent<HTMLInputElement>, index: number) => {
			const value = e.target.value;
			if (value.length === 4 && index < cardRefs.length - 1) {
				cardRefs[index + 1].current?.focus();
			}
		};

		return (
			<form className="flex flex-col gap-5 justify-center items-start">
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
							type="text"
							placeholder="YY"
							maxLength={2}
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
						type="text"
						maxLength={3}
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
						type="text"
						name="card_name"
						placeholder="Jon Dow"
						required
						className="w-3/12 px-3 py-2 border-b border-gray-500"
					/>
				</div>

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
				{isCardLinked && cardData ? <VisaInfo cardData={{}} /> : <VisaForm />}
			</div>
		</Card>
	);
}
