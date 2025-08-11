'use client';

import React from "react";
import { Button } from "@/components/ui/buttons/Buttons";

export default function Questions() {
	return (
		<div className="flex flex-col gap-5 px-40 py-10 relative w-full h-fit">
			<img src="/images/decorations/pricing-faq-bottom-right.webp" className="absolute right-0 bottom-0" alt="" />
			<div className="flex flex-col gap-5 max-w-[500px]">
				<h3 className="text-4xl font-bold">Часто задаваемые вопросы 👍</h3>
				<p className="text-gray-400">
					Есть вопрос, на который нет ответа? Вы можете связаться с нами по адресу
				</p>
				<Button
					onClick={() => {}}
					className="rounded-3xl w-fit mt-5 bg-neutral-800 hover:bg-indigo-500 duration-300 px-4 py-3"
				>
					Есть вопрос? Отправьте заявку
				</Button>
			</div>
		</div>
	);
}
