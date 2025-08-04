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
import Breadcrumb from "@/components/PageView/Breadcrumb";
import { FaCcMastercard } from "react-icons/fa";
import { Field, Checkbox } from "@/components/UI/Inputs/Inputs";
import { CiCircleCheck } from "react-icons/ci";
import Link from "next/link";

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

async function changeUserInfo(data: any): Promise<Number> {
	let status = 400;

	await fetchData("users/profile/", "put", data, true).then((response) => {
		if (response) {
			status = response.status;
		}
	});
	return status;
}

function CardProfile({ t, data }: { t: any; data: any }) {
	const [userData, setUserData] = useState({});
	const [userChange, setUserChange] = useState<any>({
		show: false,
		text: "",
		type: "",
		_2fa: data?.user?._2fa
	});

	useEffect(() => {
		console.log(userChange)
		if (userChange.show) {
			setTimeout(() => {
				setUserChange(() => {
					return {
						...userChange,
						show: false,
					};
				});
			}, 3000);
		}
	}, [userChange, setUserChange]);

	return (
		<Card>
			<div className="flex-grow flex flex-col gap-3">
				<div className="flex flex-col gap-2">
					<div className="flex justify-between items-center">
						<h2 className="text-xl font-bold">{t("profile.profile")} </h2>
						<i className="text-7xl text-gray-500">
							<PiUserLight />
						</i>
					</div>
					{userChange.show && (
						<div
							className={`${userChange.type === "warning" && "text-amber-400"} ${
								userChange.type === "success" && "text-green-600"
							}`}
						>
							{userChange.text}
						</div>
					)}
				</div>
				<div className="flex flex-col gap-1">
					<p className="text-gray-500">{t("profile.email")}:</p>
					<Field
						name="email"
						className="border-b rounded-none border-gray-500 flex-grow text-gray-500"
						value={data?.user?.email}
						disabled
					/>
				</div>
				<div className="flex flex-col gap-1">
					<p className="text-gray-500">{t("profile.fullname")}:</p>
					<Field
						name="first_name"
						className="border-b rounded-none border-gray-500 flex-grow"
						value={data?.user?.first_name}
						onChange={(e) => {
							setUserData((prev: any) => {
								return {
									...prev,
									first_name: e.target.value,
								};
							});
						}}
					/>
				</div>
				<div className="flex flex-col gap-1">
					<p className="text-gray-500">{t("profile.phone")}:</p>
					<Field
						name="tel"
						className="border-b rounded-none border-gray-500 flex-grow"
						value={data?.user?.tel}
						onChange={(e) => {
							setUserData((prev: any) => {
								return {
									...prev,
									tel: e.target.value,
								};
							});
						}}
					/>
				</div>
				<div className="flex flex-col gap-1">
					<p className="text-gray-500">{t("profile._2fa")}:</p>
					<Checkbox
						name="_2fa"
						className="border-b rounded-none border-gray-500 flex-grow"
						checked={data?.user?._2fa}
						onChange={(e) => {
							setUserData((prev: any) => {
								return {
									...prev,
									_2fa: e.target.checked,
								};
							});
						}}
					/>
				</div>

				<Button
					className="px-6 py-2 rounded-xl mt-5 bg-indigo-500 hover:bg-indigo-700 w-fit"
					onClick={() => {
						if (Object.keys(userData).length) {
							const responseStatus = changeUserInfo(userData).then((status) => {
								if (status === 200) {
									setUserChange({
										show: true,
										text: t("profile.user_info.user_changed"),
										type: "success",
									});
								}
							});
						} else {
							setUserChange({
								show: true,
								text: t("profile.user_info.no_data"),
								type: "warning",
							});
						}
					}}
				>
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

function CardSubscribe({ t, data }: { t: any; data: any }) {
	const CurrentPlan = () => {
		return (
			<div className="flex flex-col gap-3 w-full">
				<div className="flex justify-between items-center">
					<h2 className="text-xl font-bold">{t("profile.subscription")}</h2>
					<i className="text-7xl text-gray-500">
						<IoExitOutline />
					</i>
				</div>
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
		);
	};
	const EmptyPlan = () => {
		return (
			<div className="flex flex-col gap-3 w-full">
				<div className="flex justify-between items-center">
					<h2 className="text-xl font-bold">{t("profile.subscription")}</h2>
					<img src="/images/logo/head.svg" alt="" className="w-15" />
				</div>

				<div className="flex flex-col gap-3">
					<h3 className="text-3xl">{t("profile.plan_info.empty_title")}</h3>
					<p className="text-lg">{t("profile.plan_info.empty_text")}</p>
					<p className="text-md text-gray-400">{t("profile.plan_info.empty_text2")}</p>
					<Link href="pricing" className="text-lg text-yellow-400 hover:text-yellow-500 duration-300">
						{t("profile.pricing")}
					</Link>
				</div>
			</div>
		);
	};

	let view = null;
	if (data && data.plan) {
		view = <CurrentPlan />;
	} else if (data && !data.plan) {
		view = <EmptyPlan />;
	}

	return <Card>{view}</Card>;
}

export default function ProfilePage() {
	const { t } = useTranslation("common");
	const [profileData, setProfileData] = useState<{ plan?: boolean; user?: any }>({});

	const EmptyPlanAlert = () => {
		return (
			<div className="w-full p-10 bg-neutral-900 border border-green-700 rounded-3xl flex flex-col gap-2">
				<div className="flex gap-2 items-center">
					<h3 className="text-xl">{t("profile.plan_info.empty_alert_title")}</h3>
					<i className="text-2xl text-green-700">
						<CiCircleCheck />
					</i>
				</div>
				<p className="text-lg text-gray-400">{t("profile.plan_info.empty_alert_text")}</p>
				<p className="text-gray-400">{t("profile.plan_info.empty_alert_text2")}</p>
			</div>
		);
	};

	useEffect(() => {
		fetchData("users/profile/", "get", null, true).then((responseData) => {
			setProfileData(JSON.parse(responseData?.data));
		});
	}, [setProfileData]);

	return (
		<main className="mx-auto pt-80 pb-20 overflow-hidden relative px-4">
			<Breadcrumb />
			<div className="max-w-4xl mx-auto flex flex-col gap-3 scale-z-50">
				{!profileData?.plan && <EmptyPlanAlert />}

				<CardProfile t={t} data={profileData} />
				<CardVisa t={t} isCardLinked={false} />
				<CardSubscribe t={t} data={profileData} />
			</div>
		</main>
	);
}
