"use client";

import { style } from "framer-motion/client";
import next from "next";
import React from "react";
import { useEffect, useState, useRef, useLayoutEffect } from "react";

type Review = {
	name: string;
	role: string;
	avatar: string;
	text: string;
	rating: number;
};

const reviews: Review[] = [
	{
		name: "Алёна",
		role: "SMM",
		avatar: "🧑‍🦰",
		text: "Из 10 песен 9 записываю в телефон! Это магия ребята))",
		rating: 5,
	},
	{
		name: "Дмитрий С.",
		role: "Музыкант",
		avatar: "🧔‍♂️",
		text: "За выходные написал 20 песен. Все генерации текста отличные. Голос — это шедеврально!",
		rating: 5,
	},
	{
		name: "Jus",
		role: "Блогер",
		avatar: "🧒🏽",
		text: "EsAI не просто «заменяет» меня или кого-либо из моих авторов, он предоставляет необходимый инструмент для быстрой сборки.",
		rating: 5,
	},
	{
		name: "Lawrence Schroth",
		role: "DJ",
		avatar: "👨‍🎤",
		text: "Я не могу представить свою жизнь без EsAI. Я могу ввести сразу две генерации трека — и всё готово за 30 секунд!",
		rating: 5,
	},
	{
		name: "Ольга",
		role: "PR",
		avatar: "👩‍💼",
		text: "Интерфейс понятный, а результат звучит как студийный. Я в шоке каждый раз!",
		rating: 5,
	},
	{
		name: "Макс",
		role: "Рэп-исполнитель",
		avatar: "🧑‍🎤",
		text: "Уровень генерации текста и подачи — выше, чем у многих демо в индустрии!",
		rating: 5,
	},
	{
		name: "Кирилл",
		role: "Контентмейкер",
		avatar: "🧑‍💻",
		text: "Очень экономит время. Я перестал искать фрилансеров на тексты и голос.",
		rating: 5,
	},
	{
		name: "Таня",
		role: "Копирайтер",
		avatar: "👩‍🎨",
		text: "Даже если ты не музыкант, EsAI дарит ощущение творчества. Очень вдохновляет!",
		rating: 5,
	},
	{
		name: "Алекс",
		role: "Инфлюенсер",
		avatar: "🧔‍♂️",
		text: "Сделал трек, запостил — подписчики в восторге. Это реально работает!",
		rating: 5,
	},
	{
		name: "Лина",
		role: "Видеомейкер",
		avatar: "👩‍💻",
		text: "Под видео я теперь кладу свои собственные треки — чувствую себя артистом!",
		rating: 5,
	},
];

const ReviewCard = ({ review }: { review: Review }) => (
	<div className="min-w-[300px] max-w-sm bg-neutral-800/10 border border-gray-700 text-white p-6 rounded-xl mx-2 flex-shrink-0">
		<div className="flex items-center gap-3 mb-4">
			<div className="text-3xl">{review.avatar}</div>
			<div>
				<h3 className="font-semibold">{review.name}</h3>
				<p className="text-sm text-gray-400">{review.role}</p>
			</div>
		</div>
		<p className="text-sm mb-3 text-wrap">{review.text}</p>
		<div className="text-yellow-400">{"★".repeat(review.rating)}</div>
	</div>
);

export default function ReviewCarousel({
	startDirection = "left",
	speed = 10,
}: {
	startDirection?: "left" | "right";
	speed?: number;
}) {
	const [x, setX] = useState(0);
	const [reverse, setReverse] = useState(startDirection === "right");
	const reviewsRef = useRef<HTMLDivElement | null>(null);


	useEffect(() => {
		let animationFrame: number;
		let max = 500;


		const animate = () => {
			setX((prevX) => {
				const nextX = reverse ? prevX - speed : prevX + speed;

				if (!reverse && nextX >= max) {
					setReverse(true);
				} else if (reverse && nextX <= 10) {
					setReverse(false);
				}

				return nextX;
			});

			animationFrame = requestAnimationFrame(animate);
		};

		animationFrame = requestAnimationFrame(animate);

		return () => cancelAnimationFrame(animationFrame);
	}, [reverse, speed, reviewsRef]);

	return (
		<div
			className={`w-full bg-black py-2 flex justify-end`}
			style={{
				transform: `translateX(${x}px)`,
			}}
			ref={reviewsRef}
		>
			<div className="flex gap-4 animate-scroll-x whitespace-nowrap">
				{[...reviews, ...reviews].map((review, index) => (
					<ReviewCard key={index} review={review} />
				))}
			</div>
		</div>
	);
}
