"use client";

import React from "react";
import { Card } from "@/components/UI/Card";
import { Button } from "@/components/UI/Buttons/Buttons";
import { useTranslation } from "react-i18next";
import { PiUserLight } from "react-icons/pi";
import { RiVisaLine } from "react-icons/ri";
import { IoExitOutline } from "react-icons/io5";
import { fetchData } from "@/tools/fetchData";
import { useEffect, useState, useRef } from "react";

import { FaCcMastercard } from "react-icons/fa";
import { Field } from "@/components/UI/Inputs/Inputs";

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

function CardProfile({ t, data }: { t: any; data: any }) {
	return (
		<Card>
			<div className="flex-grow flex flex-col gap-3">
				<div className="flex justify-between items-center">
					<h2 className="text-xl font-bold">{t("profile.profile")} </h2>
					<i className="text-7xl text-gray-500">
						<PiUserLight />
					</i>
				</div>
				<div className="flex flex-col gap-1">
					<p className="text-gray-400">{t("profile.fullname")}:</p>
					<Field
						name="first_name"
						className="border-b rounded-none border-gray-500 flex-grow"
						value={data?.first_name}
					/>
				</div>
				<div className="flex flex-col gap-1">
					<p className="text-gray-400">{t("profile.email")}:</p>
					<Field
						name="email"
						className="border-b rounded-none border-gray-500 flex-grow text-gray-400"
						value={data?.email}
						disabled
					/>
				</div>
				<div className="flex flex-col gap-1">
					<p className="text-gray-400">{t("profile.phone")}:</p>
					<Field name="tel" className="border-b rounded-none border-gray-500 flex-grow" value={data?.tel} />
				</div>
				<Button className="px-6 py-2 rounded-xl mt-5 bg-indigo-500 hover:bg-indigo-700 w-fit">
					{t("profile.change")}
				</Button>
			</div>
		</Card>
	);
}

function CardVisa({ t, isCardLinked, cardData, onLinkCard, onChangeCard }: PropsVisa) {
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
			<form>
				<label>Card Number:</label>
				<br />
				{cardRefs.map((ref, i) => (
					<input
						key={i}
						type="text"
						maxLength={4}
						inputMode="numeric"
						pattern="\d*"
						ref={ref}
						onChange={(e) => handleCardInput(e, i)}
						required
					/>
				))}
				<br />
				<br />
				<label>Expiry Date:</label>
				<br />
				<input type="text" placeholder="MM" maxLength={2} inputMode="numeric" pattern="\d*" required /> /
				<input type="text" placeholder="YY" maxLength={2} inputMode="numeric" pattern="\d*" required />
				<br />
				<br />
				<label>CVV:</label>
				<br />
				<input type="text" maxLength={3} inputMode="numeric" pattern="\d*" required />
				<br />
				<br />
				<label>Name on Card:</label>
				<br />
				<input type="text" name="card_name" placeholder="FULL NAME" required />
				<br />
				<br />
				<button type="submit">Submit</button>
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
			<div className="flex-grow flex flex-col gap-3">
				<h2 className="text-xl font-bold">{t("profile.card")}</h2>

				{isCardLinked && cardData ? <VisaInfo cardData={{}} /> : <VisaForm />}
			</div>

			<div className="flex justify-center gap-3">
				<i className="text-8xl text-gray-500">
					<RiVisaLine />
				</i>
				<i className="text-8xl text-gray-500">
					<FaCcMastercard />
				</i>
			</div>
		</Card>
	);
}

function CardSubscribe({ t }: { t: any }) {
	return (
		<Card>
			<div className="flex-grow flex flex-col gap-3">
				<h2 className="text-xl font-bold">{t("profile.subscription")}</h2>
				<p>
					<strong>{t("profile.plan")}:</strong>
				</p>
				<p>
					<strong>{t("profile.price")}:</strong>
				</p>
				<p>
					<strong>{t("profile.write-off")}:</strong>
				</p>
				<Button className="px-6 py-2 rounded-xl bg-rose-500 hover:bg-rose-700 w-fit">
					{t("profile.unsubscribe")}
				</Button>
			</div>
			<div className="">
				<i className="text-7xl text-gray-500">
					<IoExitOutline />
				</i>
			</div>
		</Card>
	);
}

export default function ProfilePage() {
	const { t } = useTranslation("common");
	const [profileData, setProfileData] = useState(null);

	useEffect(() => {
		fetchData("users/profile/", "get", null, true).then((responseData) => {
			setProfileData(responseData?.data);
		});
	}, [setProfileData]);

	return (
		<main className="max-w-3xl mx-auto pt-50 pb-20 px-4 space-y-6">
			<CardProfile t={t} data={profileData} />
			<CardVisa t={t} isCardLinked={false} />
			<CardSubscribe t={t} />
		</main>
	);
}
