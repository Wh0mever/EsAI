import StudioClient from "@/components/studio/StudioClient";

// Студия «Создание мультфильмов» — флагманский раздел EsAI. Максимально
// простой конвейер «от идеи до готового мультфильма» для людей, впервые
// видящих ИИ: три больших шага (сценарий → персонажи → видео), каждый ведёт
// в чат с подходящей моделью через deep-link ?model=&q=.
export default function StudioPage() {
	return <StudioClient />;
}
