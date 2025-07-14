"use client";

import "./PricingTab.scss";
import React, { useState } from "react";
import { Button } from "../Buttons/Buttons";
import { IoIosCheckmark, IoIosClose } from "react-icons/io";
import { useTranslation } from "react-i18next";
import { t } from "i18next";

function CheckCircle() {
	return (
		<i className="block w-fit bg-green-500 rounded-full text-black text-sm">
			<IoIosCheckmark />
		</i>
	);
}
function NoCheckCircle() {
	return (
		<i className="block w-fit bg-red-500 rounded-full text-black text-sm">
			<IoIosClose />
		</i>
	);
}

function MonthlyTab({ active }: { active: boolean }) {
	return (
		<div className={`pricing-tab flex gap-5 ${active ? "active" : ""}`}>
			<div className="pricing-card min-w-[300px] max-w-[350px] bg-black rounded-3xl border border-gray-800 p-8 flex flex-col items-center gap-5 justify-between">
				<img src="/images/decorations/pricing-5-card-line.webp" alt="" className="pricing-card-line" />
				<div className="flex flex-col gap-5">
					<p className="text-center text-color-on-hover">VokaloTest</p>
					<p className="text-gray-400 text-center">Тестовый | Сыноо | Test</p>
					<h2 className="text-4xl font-bold text-center">{t('pricing.free')}</h2>

					<ul className="flex flex-col gap-5 text-sm">
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>
								<span className="text-yellow-400 font-bold">Gpt 4o mini 2024 07 18 </span>
								Открытая модель искусственного интеллекта
							</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>
								<span className="text-yellow-400 font-bold">3 </span> Шаблоны ИИ
							</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>
								<span className="text-yellow-400 font-bold">20 </span> Количество в месяц
							</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>
								<span className="text-yellow-400 font-bold">10 </span> обложек
							</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Чат ИИ</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Чат в реальном времени</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Рерайтер ИИ</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Изображения ИИ</p>
						</li>
						<li className="flex gap-3 items-center">
							<NoCheckCircle />
							<p>Диффузионные Изображения</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Мастер блогов</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Текст в речь</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Мои шаблоны</p>
						</li>
						<li className="flex gap-3 items-center">
							<NoCheckCircle />
							<p>Бесплатная поддержка</p>
						</li>
					</ul>
				</div>
				<Button
					onClick={() => {}}
					className="mt-5 py-2 px-4 rounded-lg w-fit bg-indigo-500 hover:bg-indigo-600 duration-300"
				>
					{t('pricing.startofwork')}
				</Button>
			</div>
			<div className="pricing-card min-w-[300px] max-w-[350px] bg-black rounded-3xl border border-gray-800 p-8 flex flex-col items-center gap-5 justify-between">
				<img src="/images/decorations/pricing-5-card-line.webp" alt="" className="pricing-card-line" />
				<div className="flex flex-col gap-5">
					<p className="text-center text-color-on-hover">Месяц</p>
					<p className="text-gray-400 text-center">30 дней | 30 күн | 30 days</p>
					<div className="flex gap-4 items-center justify-center">
						<h2 className="text-4xl font-bold text-center text-gray-400">3,870 с̲</h2>
						<span className="text-sm block px-2 py-1 bg-neutral-800 rounded line-through text-gray-400">
							4,300 с̲
						</span>
					</div>

					<ul className="flex flex-col gap-5 text-sm">
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>
								<span className="text-yellow-400 font-bold">Gpt 4o mini 2024 07 18 </span>
								Открытая модель искусственного интеллекта
							</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>
								<span className="text-yellow-400 font-bold">40 </span> Шаблоны ИИ
							</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>
								<span className="text-yellow-400 font-bold">Неограниченный </span> Количество в месяц
							</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>
								<span className="text-yellow-400 font-bold">Неограниченный </span> обложек
							</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Чат ИИ</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Чат в реальном времени</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Рерайтер ИИ</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Антиплагиат</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Изображения ИИ</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Диффузионные Изображения</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Мастер блогов</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Музыка</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Текст в речь</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Мои шаблоны</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Менеджер</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Бесплатная поддержка</p>
						</li>
					</ul>
				</div>

				<Button
					onClick={() => {}}
					className="mt-5 py-2 px-4 rounded-lg w-fit bg-indigo-500 hover:bg-indigo-600 duration-300"
				>
					{t('pricing.startofwork')}
				</Button>
			</div>
		</div>
	);
}

function YearlyTab({ active }: { active: boolean }) {
	const { t } = useTranslation('common');
	return (
		<div className={`pricing-tab flex gap-5 ${active ? "active" : ""}`}>
			<div className="pricing-card min-w-[300px] max-w-[350px] bg-black rounded-3xl border border-gray-800 p-8 flex flex-col items-center gap-5 justify-between">
				<img src="/images/decorations/pricing-5-card-line.webp" alt="" className="pricing-card-line" />
				<div className="flex flex-col gap-5">
					<p className="text-center text-color-on-hover">{t('pricing.yearly')}</p>
					<p className="text-gray-400 text-center">{t('pricing.getstarted')}</p>
					<h2 className="text-4xl font-bold text-center">42,914 с̲</h2>

					<ul className="flex flex-col gap-5 text-sm">
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>
								<span className="text-yellow-400 font-bold">DeepSeek V3 </span>
								Открытая модель искусственного интеллекта
							</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>
								<span className="text-yellow-400 font-bold">0 </span> Шаблоны ИИ
							</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>
								<span className="text-yellow-400 font-bold">1000 </span> Количество в месяц
							</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>
								<span className="text-yellow-400 font-bold">110 </span> обложек
							</p>
						</li>
						<li className="flex gap-3 items-center">
							<NoCheckCircle />
							<p>Чат ИИ</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Антиплагиат</p>
						</li>
						<li className="flex gap-3 items-center">
							<NoCheckCircle />
							<p>Изображения ИИ</p>
						</li>
						<li className="flex gap-3 items-center">
							<CheckCircle />
							<p>Диффузионные Изображения</p>
						</li>
						<li className="flex gap-3 items-center">
							<NoCheckCircle />
							<p>Текст в речь</p>
						</li>
						<li className="flex gap-3 items-center">
							<NoCheckCircle />
							<p>Мои шаблоны</p>
						</li>
						<li className="flex gap-3 items-center">
							<NoCheckCircle />
							<p>Менеджер</p>
						</li>
						<li className="flex gap-3 items-center">
							<NoCheckCircle />
							<p>Бесплатная поддержка</p>
						</li>
					</ul>
				</div>
				<Button
					onClick={() => {}}
					className="mt-5 py-2 px-4 rounded-lg w-fit bg-indigo-500 hover:bg-indigo-600 duration-300"
				>
					{t('pricing.startofwork')}
				</Button>
			</div>
		</div>
	);
}

export default function PricingTab() {
	const [activeTab, setActiveTab] = useState(0);
	const { t } = useTranslation('common');
	return (
		<div className="flex flex-col gap-10 w-full">
			<div className="flex items-center gap-10 px-40 py-10">
				<p className="block border-b-1 flex-auto border-gray-800"></p>
				<div className="flex bg-neutral-900 rounded-xl border border-gray-700 px-8 py-4 gap-8">
					<Button
						className={`text-sm hover:text-indigo-500 duration-300 ${activeTab === 0 ? "text-indigo-500" : ""}`}
						onClick={() => {
							setActiveTab(0);
						}}
					>
						{t('pricing.monthly')}
					</Button>
					<Button
						className={`text-sm hover:text-indigo-500 duration-300 ${activeTab === 1 ? "text-indigo-500" : ""}`}
						onClick={() => {
							setActiveTab(1);
						}}
					>
						{t('pricing.yearly')}
					</Button>
				</div>
				<p className="block border-b-1 flex-auto border-gray-800"></p>
			</div>

			<div className="pricing-tabs px-40">
				<MonthlyTab active={activeTab === 0 ? true : false} />
				<YearlyTab active={activeTab === 1 ? true : false} />
			</div>
		</div>
	);
}
