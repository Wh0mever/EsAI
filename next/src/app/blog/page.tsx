"use client";

import "@/assets/style.scss";
import NoData from "@/components/global/NoData";
import { useTranslation } from "react-i18next";
import Breadcrumb from "@/components/global/AnimatedCircleBg";
import { useEffect, useState } from "react";
import { fetchData } from "@/tools/fetchData";
import { API } from "@/tools/fetchData";

async function blogPosts() {
	return await fetchData("content/blog/", "get", null, false);
}

export default function Blog() {
	const { t, i18n } = useTranslation("common");
	const [posts, setPosts] = useState([]);
	const points = t("blog.points", { returnObjects: true }) as string[];
	const lang = i18n.language;

	useEffect(() => {
		blogPosts().then((response) => {
			setPosts(response?.data || []);
		});
	}, []);

	const PostElement = ({ post }: { post: any }) => {
		const title = post[`title_${lang}`] || post.title_en;
		const content = post[`content_${lang}`] || post.content_en;

		return (
			<article className="border border-neutral-700 rounded-xl p-6 shadow-md mb-8 bg-neutral-950">
				{post.image && (
					<div className="mb-4">
						<img
							src={`http://127.0.0.1:8000${post.image}`}
							alt={title}
							className="rounded-lg object-cover w-full h-auto"
						/>
					</div>
				)}
				<h2 className="text-2xl font-semibold mb-2">{title}</h2>
				<p className="text-gray-700 dark:text-gray-400">{content}</p>
				<div className="flex justify-between text-gray-500">
					<p>{new Date(post.created_at).toLocaleDateString()}</p>
					<p>{post.author}</p>
				</div>
			</article>
		);
	};

	const PostView = () => {
		if (!posts.length) {
			return <NoData />;
		}

		return (
			<div className="grid gap-6">
				{posts.map((post: any) => (
					<PostElement key={post.id} post={post} />
				))}
			</div>
		);
	};

	return (
		<main className="mx-auto pt-80 overflow-hidden relative px-4">
			<Breadcrumb />

			<div className="mx-auto max-w-4xl px-4 py-4">
				<section className="py-10">
					<h1 className="text-3xl font-bold text-center">{t("blog.title")}</h1>
					<p className="text-center text-gray-700 dark:text-gray-300 text-base my-10">{t("blog.subtitle")}</p>

					<ul className="space-y-3 list-disc pl-6 text-gray-800 dark:text-gray-200">
						{points.map((item, index) => (
							<li key={index}>{item}</li>
						))}
					</ul>

					<p className="mt-10 text-center text-gray-600 dark:text-gray-400">{t("blog.footer")}</p>
				</section>

				<section className="py-12">
					<PostView />
				</section>
			</div>
		</main>
	);
}
