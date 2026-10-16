import type { StudioCharacter } from "../CharacterPicker";

/**
 * Порядок карточек в ленте героев.
 *
 * Сначала герои открытого мультфильма: следующую сцену чаще снимают кем-то из
 * уже занятых. Затем выбранный, если фильтр аудитории его спрятал, — иначе
 * человек не видел бы, с кем сейчас показываются сцены. Дальше свои (клиент:
 * их ищут первыми) и библиотечные. Каждый герой — один раз.
 */
export function heroOrder(
  heroes: StudioCharacter[],
  cast: StudioCharacter[],
  selected: StudioCharacter | null,
): StudioCharacter[] {
  const seen = new Set<number>();
  const out: StudioCharacter[] = [];
  const push = (c: StudioCharacter) => {
    if (seen.has(c.id)) return;
    seen.add(c.id);
    out.push(c);
  };
  cast.forEach(push);
  if (selected && !heroes.some((c) => c.id === selected.id)) push(selected);
  heroes.filter((c) => c.is_mine).forEach(push);
  heroes.filter((c) => !c.is_mine).forEach(push);
  return out;
}
