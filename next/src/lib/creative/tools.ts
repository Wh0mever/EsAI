// Реестр 15 инструментов Creative Studio — на стороне сайта.
//
// Название, описание, категория и номер карточки меняются здесь, без правки
// логики: клиент ещё будет их двигать. Подписи — пространство `creative`
// (locales/*/creative.json, ключи tools.<id>.name / .desc); русский текст
// продублирован здесь как запасной, пока перевод не подгрузился.
//
// Модели поставщика здесь намеренно нет: этот файл уходит в браузер, а
// поставщика в интерфейсе не называем (ТЗ v8.1). Сопоставление карточка →
// модель живёт на сервере (этап B1), см. раздел 6 плана.
import type { CreativeCategory } from "@/lib/nav/menu";

export type ToolState = "soon" | "live";

export type CreativeTool = {
  /** адрес /creative/<id> */
  id: string;
  /** номер карточки на макете */
  n: number;
  cat: CreativeCategory;
  name: string;
  desc: string;
  /** что получает человек: картинку или видео */
  output: "image" | "video";
  /** превью карточки: базовый путь в /public без размера — рядом лежат <путь>-320.webp,
   *  -480.webp и -960.webp (16:9). null — заглушка по цвету категории. */
  img: string | null;
  state: ToolState;
};

export const CREATIVE_TOOLS: CreativeTool[] = [
  { id: "motion-transfer", n: 1, cat: "video", output: "video", img: "/images/creative/tools/motion-transfer", state: "live",
    name: "Перенос движения", desc: "Оживи персонажа из фото с помощью видео" },
  { id: "object-swap", n: 2, cat: "video", output: "video", img: "/images/creative/tools/object-swap", state: "live",
    name: "Замена объекта", desc: "Замени любой объект в видео" },
  { id: "restyle", n: 3, cat: "video", output: "video", img: "/images/creative/tools/restyle", state: "live",
    name: "Изменение стиля", desc: "Преобразуй видео в другом стиле" },
  { id: "character-motion", n: 4, cat: "video", output: "video", img: "/images/creative/tools/character-motion", state: "live",
    name: "Движение персонажа", desc: "Задай новые движения персонажу" },
  { id: "item-swap", n: 5, cat: "video", output: "video", img: "/images/creative/tools/item-swap", state: "live",
    name: "Замена предмета", desc: "Замени объект на другой (например, на товар)" },
  // Карточка 6: клиент 16.11 заменил «Перестилизацию видео» (дубль Restyle) на
  // рекламный генератор. Проверка 23.11: результат — картинки (реклама с текстом),
  // не ролик, поэтому output "image" и описание про картинки.
  { id: "ad-creative", n: 6, cat: "ads", output: "image", img: "/images/creative/tools/ad-creative", state: "live",
    name: "Рекламный креатив", desc: "Готовые рекламные картинки для вашего товара" },
  { id: "photo-restyle", n: 7, cat: "image", output: "image", img: "/images/creative/tools/photo-restyle", state: "live",
    name: "Преобразование фото", desc: "Преврати фото в профессиональном стиле (студия, fashion, кино)" },
  { id: "text-to-image", n: 8, cat: "image", output: "image", img: "/images/creative/tools/text-to-image", state: "live",
    name: "Создание по описанию", desc: "Создай уникальное изображение по текстовому описанию" },
  // Описание по ответу клиента 16.11: это лист персонажа (изображение), не видео.
  { id: "virtual-blogger", n: 9, cat: "characters", output: "image", img: "/images/creative/tools/virtual-blogger", state: "live",
    name: "Виртуальный блогер", desc: "Создай лист виртуального персонажа: внешность, ракурсы и образы" },
  { id: "consistent-character", n: 10, cat: "characters", output: "image", img: "/images/creative/tools/consistent-character", state: "live",
    name: "Постоянный персонаж", desc: "Создай героя в разных образах и локациях" },
  { id: "portrait", n: 11, cat: "image", output: "image", img: "/images/creative/tools/portrait", state: "live",
    name: "Фотореалистичный портрет", desc: "Создай реалистичный портрет студийного качества" },
  { id: "ad-campaign", n: 12, cat: "ads", output: "image", img: "/images/creative/tools/ad-campaign", state: "live",
    name: "Рекламная кампания", desc: "Серия готовых визуалов для продвижения товара" },
  { id: "ad-poster", n: 13, cat: "ads", output: "image", img: "/images/creative/tools/ad-poster", state: "live",
    name: "Рекламный постер", desc: "Создай эффектный постер с текстом и брендингом" },
  { id: "product-ad", n: 14, cat: "ads", output: "image", img: "/images/creative/tools/product-ad", state: "live",
    name: "Премиальная предметная реклама", desc: "Рекламный кадр товара с динамикой и светом" },
  { id: "script-to-video", n: 15, cat: "video", output: "video", img: "/images/creative/tools/script-to-video", state: "live",
    name: "Сценарий в видео", desc: "Преврати идею или сценарий в готовое видео" },
];

export const toolById = (id: string) => CREATIVE_TOOLS.find((t) => t.id === id);

export const isCategory = (v: string | null | undefined): v is CreativeCategory =>
  v === "video" || v === "image" || v === "characters" || v === "ads";
