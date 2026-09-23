import { redirect } from "next/navigation";

// Раздел «Кейсы» так и не наполнили: по адресу /case стояла голая строка
// «Case Page». Пока контента нет — уводим на главную (в sitemap её нет,
// layout помечен noindex).
export default function Case() {
	redirect("/");
}
