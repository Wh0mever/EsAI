/**
 * Цели Яндекс.Метрики.
 *
 * Счётчик инициализируется в app/layout.tsx, там же заглушка `ym`, которая
 * копит вызовы до загрузки tag.js. Из-за этой заглушки вызов «проходит» даже
 * тогда, когда отправить его ещё нечем: если сразу после цели увести
 * пользователя на другую страницу, накопленная очередь пропадёт вместе с
 * документом. Поэтому здесь есть колбэк — дождаться реальной отправки и
 * только потом уходить.
 */

const YM_COUNTER_ID = 111652637;

/**
 * Отправить цель. `onDone` вызывается РОВНО ОДИН РАЗ: либо когда Метрика
 * подтвердила отправку, либо по таймауту — чтобы переход не завис, если
 * счётчик заблокирован блокировщиком рекламы или не загрузился.
 */
export function ymReachGoal(goal: string, onDone?: () => void, timeoutMs = 1000): void {
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    onDone?.();
  };

  try {
    const ym = (globalThis as any).ym;
    if (typeof ym !== "function") {
      finish();
      return;
    }
    // Сигнатура: ym(id, 'reachGoal', target, params, callback)
    ym(YM_COUNTER_ID, "reachGoal", goal, undefined, finish);
  } catch {
    finish();
    return;
  }

  if (onDone) window.setTimeout(finish, timeoutMs);
}

/**
 * Цель «Регистрация в EsAI» (создана клиентом в Метрике).
 *
 * Вызывать ТОЛЬКО когда аккаунт действительно создан — то есть на ответе
 * сервера с признаком нового пользователя, а не по нажатию кнопки «Войти».
 */
export function trackRegistration(onDone?: () => void): void {
  ymReachGoal("registration", onDone);
}
