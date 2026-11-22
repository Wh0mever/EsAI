import "@/assets/style.scss";
import { preload } from "react-dom";
import HomeHub from "@/components/landing/HomeHub";

export default function HomePreviewPage() {
	// Кот на первом экране — LCP; клиентская часть появляется после загрузки
	// переводов, поэтому браузеру подсказываем картинку заранее (своя для телефона).
	preload("/images/home/cat-esai-m-800.webp", { as: "image", fetchPriority: "high", media: "(max-width: 767px)" });
	preload("/images/home/cat-esai-1280.webp", {
		as: "image",
		fetchPriority: "high",
		imageSrcSet: "/images/home/cat-esai-768.webp 768w, /images/home/cat-esai-1280.webp 1280w",
		imageSizes: "(min-width: 1280px) 1280px, 100vw",
		media: "(min-width: 768px)",
	});
	return <HomeHub />;
}
