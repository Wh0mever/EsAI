import type { Metadata } from "next";
import VideoStudio from "@/components/vstudio/VideoStudio";
import { SITE_URL } from "@/lib/seo/site";

export const metadata: Metadata = {
	alternates: { canonical: `${SITE_URL}/video-studio` },
};

// Новая генерация: первый запуск создаёт проект, и адрес сменится на
// /video-studio/<uid> без перезагрузки (студия при этом не пересоздаётся).
export default function VideoStudioPage() {
	return <VideoStudio projectUid={null} />;
}
