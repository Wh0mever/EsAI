import type { Metadata } from "next";
import VideoStudio from "@/components/vstudio/VideoStudio";

// Проект — личная страница: в поиск не попадает (и robots закрывает /video-studio/).
export const metadata: Metadata = {
	robots: { index: false, follow: false },
};

type Params = { project: string };

/**
 * Проект видеостудии: /video-studio/<uid>. ?take=<uid> прокручивает к карточке
 * дубля (ссылка из пуша и тоста «готово»). Кривой uid сюда тоже доходит —
 * студия покажет «Проект не найден», запрос с ним не уйдёт вовсе.
 */
export default async function VideoStudioProjectPage({ params }: { params: Promise<Params> }) {
	const { project } = await params;
	return <VideoStudio projectUid={project} />;
}
