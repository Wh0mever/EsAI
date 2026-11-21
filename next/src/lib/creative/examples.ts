// Галерея примеров на странице Creative Studio (якорь #examples).
// Сюда ведёт кнопка «Посмотреть примеры» с главной (решение клиента 16.11).
//
// Только реальные результаты наших инструментов, одобренные клиентом:
// пробные запросы (этап B0) и первые настоящие генерации. Чужие ролики и
// картинки поставщика не брать. Пока список пуст, блок не выводится, а кнопка
// на главной ведёт просто на /creative.
export type CreativeExample = {
  /** id инструмента из lib/creative/tools.ts */
  tool: string;
  kind: "image" | "video";
  /** файл в /public/images/creative/examples/ */
  src: string;
  /** превью для видео */
  poster?: string;
  /** подпись (русская; перевод — в creative.json, ключ examples.<n>) */
  caption: string;
};

export const CREATIVE_EXAMPLES: CreativeExample[] = [];

export const HAS_EXAMPLES = CREATIVE_EXAMPLES.length > 0;
