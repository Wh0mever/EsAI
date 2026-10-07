/**
 * Сколько роликов первого экрана играет одновременно.
 *
 * На экране могут оказаться карусель и десяток карточек галереи; заводить все
 * сразу — лишний трафик на мобильной сети и лишняя работа телефону (§0.8).
 * Поэтому каждый LazyClip сначала просит место: всего их MAX_PLAYING, первым
 * пришёл — первым играет, остальные показывают постер и ждут, пока место
 * освободится. Активному кадру карусели место находится всегда — за счёт
 * карточки, которая попросила последней.
 *
 * Реестр один на вкладку (модуль, а не компонент): карусель и галерея ничего
 * не знают друг о друге. Модуль чистый, без React и DOM, — его проверяет
 * node-тест playBudget.test.mjs.
 */

export const MAX_PLAYING = 4;

/** Биты playState: место выдано / запущен нажатием / браузер запретил автозапуск. */
export const PLAY_ON = 1;
export const PLAY_SOLO = 2;
export const PLAY_BLOCKED = 4;

type Claim = {
  /** Порядок заявок: кто раньше попросил, тот раньше играет. */
  seq: number;
  priority: boolean;
  /** Запущен нажатием на кнопку, а не сам. */
  solo: boolean;
};

const claims = new Map<string, Claim>();
let granted: ReadonlySet<string> = new Set();
let blocked = false;
let seq = 0;
const listeners = new Set<() => void>();

const rank = (c: Claim) => (c.solo ? 2 : c.priority ? 1 : 0);

function settle(): void {
  const order = [...claims.entries()].sort(([, a], [, b]) => rank(b) - rank(a) || a.seq - b.seq);
  granted = new Set(order.slice(0, MAX_PLAYING).map(([id]) => id));
  for (const l of [...listeners]) l();
}

/** Ролик готов играть сам (виден, наведён, активен). id — useId экземпляра; priority — активный кадр карусели. */
export function requestPlay(id: string, priority = false): void {
  const cur = claims.get(id);
  if (cur && cur.priority === priority) return;
  claims.set(id, cur ? { ...cur, priority } : { seq: ++seq, priority, solo: false });
  settle();
}

/**
 * Ролик запустили нажатием. Прежний запущенный так же останавливается: при
 * выключенном автозапуске человек смотрит один ролик, а не собирает коллекцию.
 */
export function requestSolo(id: string): void {
  for (const [other, claim] of claims) if (claim.solo && other !== id) claims.delete(other);
  const cur = claims.get(id);
  claims.set(id, { seq: cur ? cur.seq : ++seq, priority: cur ? cur.priority : false, solo: true });
  settle();
}

/** Условие автозапуска пропало (увели курсор). Запущенный нажатием продолжает играть. */
export function releaseAuto(id: string): void {
  const cur = claims.get(id);
  if (!cur || cur.solo) return;
  claims.delete(id);
  settle();
}

/** Ролик больше не должен играть вовсе: ушёл с экрана, перестал быть активным, размонтирован. */
export function releasePlay(id: string): void {
  if (claims.delete(id)) settle();
}

/**
 * Браузер отказал в автозапуске (режим энергосбережения iOS, запрет в
 * настройках). Это правило устройства, а не случайность одного ролика: дальше
 * никто не пробует сам — все показывают кнопку.
 */
export function markAutoplayBlocked(): void {
  if (blocked) return;
  blocked = true;
  for (const [id, claim] of claims) if (!claim.solo) claims.delete(id);
  settle();
}

/** Состояние ролика одним числом (для useSyncExternalStore): биты PLAY_*. */
export function playState(id: string): number {
  const claim = claims.get(id);
  return (granted.has(id) ? PLAY_ON : 0) | (claim?.solo ? PLAY_SOLO : 0) | (blocked ? PLAY_BLOCKED : 0);
}

export function subscribePlay(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}

/** Для тестов: забыть все заявки и запрет автозапуска. */
export function resetPlayBudget(): void {
  claims.clear();
  granted = new Set();
  blocked = false;
  seq = 0;
  for (const l of [...listeners]) l();
}
