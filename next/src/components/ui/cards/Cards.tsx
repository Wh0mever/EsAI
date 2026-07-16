"use client";

import React, { useState, useEffect } from "react";
import { CiHeart } from "react-icons/ci";
import { BsStars } from "react-icons/bs";
import { Button } from "@/components/ui/buttons/Buttons";
import { t } from "i18next";
import { fetchData } from "@/tools/fetchData";
import { body } from "framer-motion/client";

interface ICard {
	children: React.ReactNode;
}

export function Card({ children }: ICard) {
	return <div className="bg-surface p-10 rounded-4xl flex gap-2 items-center">{children}</div>;
}

export function TemplateCard({ template, localTemplates, setLocalTemplates }: any) {
	const [isFavorite, setIsFavorite] = useState(false);
	const [isUsed, setIsUsed] = useState(false);

	const provider = template?.provider_name ?? template?.provider ?? "GPT";

	function handleUseTemplate() {
		setLocalTemplates((prev: any) => {
			const next = { ...(prev || {}) };
			if (next[provider]?.id === template.id) {
				delete next[provider];
			} else {
				next[provider] = template;
			}
			return next;
		});
	}

	function handleFavorite() {
		setIsFavorite(!isFavorite);
		fetchData("ai/templates/favorite/", "POST", {
			templateId: template.id,
			favorite: !isFavorite,
		}).then();
	}

	useEffect(() => {
		const used = localTemplates?.[provider];
		setIsUsed(!!used && used.id === template.id);
	}, [localTemplates, provider, template?.id]);

	return (
		<div
			className="flex flex-col gap-3 p-10 card-hover-colored bg-gray-800/5 border border-gray-700 rounded-xl hover:shadow-lg hover:bg-gray-800/10 hover:border-gray-600 colored-center"
			style={{ animation: "showCard 0.5s ease-in-out forwards" }}
		>
			<img
				src="/images/decorations/ai-template-card-bg.webp"
				alt=""
				className="absolute h-full w-full left-0 top-0 -z-10"
			/>
			<i className="text-3xl p-5 flex rounded-full w-fit h-fit bg-accent-soft text-accent">
				<BsStars />
			</i>
			<div>
				<h3 className="text-white font-semibold text-lg">
					{provider} - {template?.name}
				</h3>
				{template?.description && <p className="text-gray-400 text-sm mt-1">{template?.description}</p>}
			</div>
			<div className="text-gray-500 flex items-center justify-between mt-3">
				<div className="text-sm">
					<p className="text-gray-300">
						<span>{t("chat.templates.usage")}: </span>
						<span>{template?.usage_count}</span>
					</p>
					{template?.id && (
						<Button
							className={`text-sm ${
								isUsed
									? "text-yellow-500 hover:text-yellow-600"
									: "text-accent hover:text-accent-strong"
							}`}
							onClick={handleUseTemplate}
						>
							{isUsed ? t("chat.templates.templateUsed") : t("chat.templates.useTemplate")}
						</Button>
					)}
				</div>
				<Button
					className={`text-2xl cursor-pointer flex items-center justify-center p-3 rounded-full transition-colors ${
						isFavorite
							? "text-rose-400 hover:text-rose-600 hover:bg-white/75"
							: "text-gray-400 hover:text-accent hover:bg-white/75"
					}`}
					onClick={() => {
						handleFavorite();
					}}
				>
					<CiHeart className="inline-block mr-1" />
				</Button>
			</div>
		</div>
	);
}
