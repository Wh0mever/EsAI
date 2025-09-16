"use client";

import React, { useEffect, useState, useRef } from "react";
import { Card } from "@/components/ui/cards/Cards";
import { Button } from "@/components/ui/buttons/Buttons";
import { Field, Checkbox } from "@/components/ui/inputs/Inputs";
import { PiUserLight } from "react-icons/pi";
import { fetchData } from "@/tools/fetchData";
import { ConfirmationModal } from "@/components/dialog/Dialog";
import Cookies from "js-cookie";

async function changeUserInfo(data: any): Promise<Number> {
	let status = 400;

	await fetchData("users/profile/", "put", data, true).then((response) => {
		if (response) {
			status = response.status;
		}
	});
	return status;
}

export default function UserProfile({ t, data }: { t: any; data: any }) {
	const [userData, setUserData] = useState({});
	const [userChange, setUserChange] = useState<any>({
		show: false,
		text: "",
		type: "",
		_2fa: data?.user?._2fa,
	});

	const [isLogoutConfirmModalOpen, setLogoutConfirmModalOpen] = useState(false);

	useEffect(() => {
		console.log(userChange);
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

	function handleLogout() {
		Cookies.remove("access");
		Cookies.remove("refresh");
		Cookies.remove("user");
		Cookies.remove("sessionid");
		window.location.href = "/auth/signin";
	}

	return (
		<Card>
			<div className="flex-grow flex flex-col gap-3">
				<div className="flex flex-col gap-2">
					<div className="flex justify-between items-center">
						<h2 className="text-xl font-bold">{t("profile.profile")} </h2>
						<div className="flex items-center gap-2">
							<i className="text-7xl text-gray-500">
								<PiUserLight />
							</i>
						</div>
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

				<div className="flex gap-3 items-center mt-5">
					<Button
						className="px-6 py-2 rounded-xl bg-indigo-500 hover:bg-indigo-700 w-fit"
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

					<Button
						className="px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-700"
						onClick={() => setLogoutConfirmModalOpen(true)}
					>
						{t("nav.logout")}
					</Button>
				</div>
			</div>
			{/* Logout confirmation modal */}
			<ConfirmationModal
				isOpen={isLogoutConfirmModalOpen}
				title={t("nav.logOutConfirmTitle")}
				confirmText={t("common.yes")}
				cancelText={t("common.no")}
				onConfirm={handleLogout}
				onCancel={() => setLogoutConfirmModalOpen(false)}
			/>
		</Card>
	);
}
