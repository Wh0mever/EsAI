"use client";

import React, { useEffect, useRef, useState } from "react";
import Image from "next/image";
import Radar from "@/components/global/Radar";
import { TextChangingTag } from "@/components/ui/text/Text";

const IMAGE_WIDTH = 120;
const IMAGE_HEIGHT = 100;
const IMAGE_COUNT = 23;

function getImagePath(index: number) {
	return `/images/decorations/aigenerated/${index}.webp`;
}

function shuffleArray<T>(array: T[]): T[] {
	return [...array].sort(() => Math.random() - 0.5);
}

function InfiniteScroll({
	images,
	direction = "right",
	bounce = false,
	speed = 1,
	fps = 60,
}: {
	images: string[];
	direction?: "left" | "right";
	bounce?: boolean;
	speed?: number;
	fps?: number;
}) {
	const containerRef = useRef<HTMLDivElement>(null);
	const [offset, setOffset] = useState(0);
	const [dir, setDir] = useState(direction);

	useEffect(() => {
		const interval = setInterval(() => {
			const container = containerRef.current;
			if (!container) return;

			const maxScroll = images.length * IMAGE_WIDTH;
			setOffset((prev) => {
				let next = dir === "right" ? prev + speed : prev - speed;

				if (bounce) {
					if (next >= maxScroll - container.clientWidth) setDir("left");
					if (next <= 0) setDir("right");
				} else {
					if (next >= maxScroll) next = 0;
					if (next <= -maxScroll) next = 0;
				}

				return next;
			});
		}, 1000 / fps);

		return () => clearInterval(interval);
	}, [dir, images.length, bounce, speed, fps]);

	return (
		<div className="overflow-hidden w-full h-[100px]">
			<div
				ref={containerRef}
				className="flex gap-2"
				style={{
					transform: `translateX(-${offset}px)`,
					transition: `transform 0.1s ease-in-out`,
				}}
			>
				{images.map((src, i) => (
					<div
						key={i}
						className="relative"
						style={{ width: IMAGE_WIDTH, height: IMAGE_HEIGHT, flexShrink: 0 }}
					>
						<Image
							src={src}
							alt={`AI ${i + 1}`}
							fill
							sizes={`${IMAGE_WIDTH}px`}
							className="object-cover rounded-md"
						/>
					</div>
				))}
				{!bounce &&
					images.map((src, i) => (
						<div
							key={`copy-${i}`}
							className="relative"
							style={{ width: IMAGE_WIDTH, height: IMAGE_HEIGHT, flexShrink: 0 }}
						>
							<Image
								src={src}
								alt={`AI copy ${i + 1}`}
								fill
								sizes={`${IMAGE_WIDTH}px`}
								className="object-cover rounded-md"
							/>
						</div>
					))}
			</div>
		</div>
	);
}

export default function AIGalleryStrips() {
	const [images1, setImages1] = useState<string[]>([]);
	const [images2, setImages2] = useState<string[]>([]);
	const [images3, setImages3] = useState<string[]>([]);

	useEffect(() => {
		const indices = Array.from({ length: IMAGE_COUNT }, (_, i) => i + 1);

		const s1 = shuffleArray(indices);
		const s2 = shuffleArray(indices);
		const s3 = shuffleArray(indices);

		setImages1(s1.map(getImagePath));
		setImages2(s2.map(getImagePath));
		setImages3(s3.map(getImagePath));
	}, []);

	if (!images1.length || !images2.length || !images3.length) return null;

	return (
		<div className="flex flex-col gap-4 relative">
			<div className="absolute z-100 w-full h-full flex items-center justify-center">
				<div className="px-4 py-2 min-w-22 flex items-center justify-center absolute top-5">
					<TextChangingTag className="text-white" />
				</div>

				<Radar />
			</div>
			<InfiniteScroll images={images1} direction="right" speed={0.7} />
			<InfiniteScroll images={images2} direction="left" speed={0.8} />
			<InfiniteScroll images={images3} direction="right" bounce speed={0.6} />
		</div>
	);
}
