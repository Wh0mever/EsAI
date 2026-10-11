// Видеостудия, панель запроса: «водитель» свёрнутого поля (composer/foldDriver.ts) —
// порядок событий браузера: нажали, фокус ушёл, отпустили, пауза; окошки, окно без фокуса.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/vstudio/composer/foldDriver.test.mjs
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const { createFoldDriver } = await import("./foldDriver.ts");
const { FOLD_LEAVE_MS, lastKnown } = await import("./promptFold.ts");

/** Панель «на столе»: свои часы, фокус, выделение и окошки — всё крутится руками. */
function bench(fold = "rest") {
  const env = { now: 0, timers: [], seq: 0, focus: false, selected: false, held: false, commits: [] };
  const driver = createFoldDriver(
    {
      commit: (f) => env.commits.push(f),
      focused: () => env.focus,
      selection: () => env.selected,
      held: () => env.held,
      setTimer: (fn, ms) => {
        const id = ++env.seq;
        env.timers.push({ id, at: env.now + ms, fn });
        return id;
      },
      clearTimer: (id) => {
        env.timers = env.timers.filter((t) => t.id !== id);
      },
    },
    fold,
  );
  /** Прошло ms: таймеры срабатывают по порядку. */
  const tick = (ms) => {
    const until = env.now + ms;
    for (;;) {
      const next = env.timers.filter((t) => t.at <= until).sort((a, b) => a.at - b.at)[0];
      if (!next) break;
      env.timers = env.timers.filter((t) => t !== next);
      env.now = next.at;
      next.fn();
    }
    env.now = until;
  };
  // Фокус в поле / на кнопке панели / вне панели — как это видит браузер.
  const focusField = () => {
    env.focus = true;
    driver.focusIn(true);
  };
  const focusButton = () => {
    env.focus = true;
    driver.focusIn(false);
  };
  const blur = (windowFocused = true) => {
    if (windowFocused) env.focus = false;
    driver.focusOut(windowFocused);
  };
  const fold_ = () => driver.state().fold;
  return { env, driver, tick, focusField, focusButton, blur, fold: fold_ };
}

/** Поле развёрнуто, курсор в нём. */
function typing() {
  const b = bench();
  b.focusField();
  assert.equal(b.fold(), "open");
  return b;
}

test("ушёл кликом мимо панели: поле сворачивается через паузу после отпускания, не раньше", () => {
  const b = typing();
  b.driver.pointerDown(1);
  b.blur();
  b.tick(100);
  b.driver.pointerUp(1);
  // Пауза считается от отпускания, а не от нажатия.
  b.tick(FOLD_LEAVE_MS - 1);
  assert.equal(b.fold(), "open");
  b.tick(1);
  assert.equal(b.fold(), "rest");
  assert.deepEqual(b.env.commits, ["open", "rest"]);
  assert.equal(b.env.timers.length, 0);
});

test("держат кнопку мыши дольше паузы — поле ждёт отпускания", () => {
  const b = typing();
  b.driver.pointerDown(1);
  b.blur();
  b.tick(FOLD_LEAVE_MS * 4);
  assert.equal(b.fold(), "open");
  b.driver.pointerUp(1);
  b.tick(FOLD_LEAVE_MS);
  assert.equal(b.fold(), "rest");
});

test("ушёл с клавиатуры (Tab за панель): пауза и сворачивание", () => {
  const b = typing();
  b.blur();
  b.tick(FOLD_LEAVE_MS);
  assert.equal(b.fold(), "rest");
});

test("клик по кнопке панели (Chrome: фокус переходит на кнопку) поле не сворачивает", () => {
  const b = typing();
  b.driver.pointerDown(1);
  b.driver.pressedInside();
  b.blur();
  b.focusButton();
  b.driver.pointerUp(1);
  b.tick(FOLD_LEAVE_MS * 10);
  assert.equal(b.fold(), "open");
  assert.equal(b.env.timers.length, 0);
  // Дальше — обычный уход: с кнопки фокус ушёл за панель.
  b.blur();
  b.tick(FOLD_LEAVE_MS);
  assert.equal(b.fold(), "rest");
});

test("клик по кнопке панели (Safari: фокус уходит в никуда) — тоже не уход; уход — нажатие мимо панели", () => {
  const b = typing();
  b.driver.pointerDown(1);
  b.driver.pressedInside();
  b.blur();
  b.driver.pointerUp(1);
  b.tick(FOLD_LEAVE_MS * 10);
  assert.equal(b.fold(), "open");
  // Фокуса в панели нет, blur уже не придёт: уход узнаём по нажатию мимо неё.
  b.driver.pointerDown(2);
  b.tick(FOLD_LEAVE_MS * 2);
  assert.equal(b.fold(), "open");
  b.driver.pointerUp(2);
  b.tick(FOLD_LEAVE_MS);
  assert.equal(b.fold(), "rest");
});

test("Tab с поля на кнопку панели: уход отменяется, таймера не остаётся", () => {
  const b = typing();
  b.blur();
  assert.equal(b.env.timers.length, 1);
  b.focusButton();
  assert.equal(b.env.timers.length, 0);
  b.tick(FOLD_LEAVE_MS * 4);
  assert.equal(b.fold(), "open");
});

test("кнопка под фокусом выключилась («Создать» на время отправки): фокус пропал без blur, поле на месте", () => {
  const b = typing();
  b.driver.pointerDown(1);
  b.driver.pressedInside();
  b.blur();
  b.focusButton();
  b.driver.pointerUp(1);
  // Кнопка выключена: браузер снял с неё фокус молча.
  b.env.focus = false;
  b.tick(FOLD_LEAVE_MS * 4);
  // Запуск отклонён — поле осталось развёрнутым; нажатие мимо панели его сворачивает.
  assert.equal(b.fold(), "open");
  b.driver.pointerDown(2);
  b.driver.pointerUp(2);
  b.tick(FOLD_LEAVE_MS);
  assert.equal(b.fold(), "rest");
});

test("клик в свёрнутое поле: текст не едет под нажатой кнопкой, разворот — по отпусканию", () => {
  const b = bench();
  b.driver.pointerDown(1);
  b.driver.pressedInside();
  b.focusField();
  assert.equal(b.fold(), "rest");
  assert.deepEqual(b.env.commits, []);
  b.driver.pointerUp(1);
  assert.equal(b.fold(), "open");
  b.tick(FOLD_LEAVE_MS * 4);
  assert.equal(b.fold(), "open");
});

test("телефон: касание свёрнутого поля — фокус приходит после отпускания, разворот сразу", () => {
  const b = bench();
  b.driver.pointerDown(7);
  b.driver.pressedInside();
  b.driver.pointerUp(7);
  assert.equal(b.fold(), "rest");
  b.focusField();
  assert.equal(b.fold(), "open");
});

test("телефон: прокрутка ленты пальцем (pointercancel) — тоже конец нажатия", () => {
  const b = typing();
  b.driver.pointerDown(3);
  b.blur();
  // pointercancel приходит той же ручкой, что и pointerup.
  b.driver.pointerUp(3);
  b.tick(FOLD_LEAVE_MS);
  assert.equal(b.fold(), "rest");
});

test("кнопки панели свёрнутое поле не разворачивают: чип параметра нажали — текст на месте", () => {
  const b = bench();
  b.driver.pointerDown(1);
  b.driver.pressedInside();
  b.focusButton();
  b.driver.pointerUp(1);
  b.tick(FOLD_LEAVE_MS * 4);
  assert.equal(b.fold(), "rest");
  assert.deepEqual(b.env.commits, []);
});

test("окошко панели открыто: поле ждёт, пока его закроют, и ещё паузу", () => {
  const b = typing();
  b.blur();
  b.env.held = true;
  b.driver.holdChanged();
  b.tick(FOLD_LEAVE_MS * 4);
  assert.equal(b.fold(), "open");
  b.env.held = false;
  b.driver.holdChanged();
  b.tick(FOLD_LEAVE_MS - 1);
  assert.equal(b.fold(), "open");
  b.tick(1);
  assert.equal(b.fold(), "rest");
});

test("раскладка цены ещё висит (наведение), а человек уже кликнул в ленту: уход считается, когда она закрылась", () => {
  const b = typing();
  b.env.held = true;
  b.driver.holdChanged();
  // Клик мимо панели при открытом окошке: фокус ушёл, но окошко — ещё «панель».
  b.driver.pointerDown(1);
  b.blur();
  b.driver.pointerUp(1);
  b.tick(FOLD_LEAVE_MS * 2);
  assert.equal(b.fold(), "open");
  assert.equal(b.driver.state().leaving, false);
  // Окошко закрылось само — в панели никого.
  b.env.held = false;
  b.driver.holdChanged();
  b.tick(FOLD_LEAVE_MS);
  assert.equal(b.fold(), "rest");
});

test("кликнул в поле мышью, а ушёл клавишей Tab, пока раскладка цены ещё висела: уход не теряется", () => {
  // Tab до «Создать» (раскладка открылась по фокусу) и дальше, за панель.
  const tab = bench();
  tab.driver.pointerDown(1);
  tab.driver.pressedInside();
  tab.focusField();
  tab.driver.pointerUp(1);
  tab.blur();
  tab.focusButton();
  tab.env.held = true;
  tab.driver.holdChanged();
  tab.blur();
  // Раскладка ещё на экране: фокус ушёл, но уходом это пока не считается.
  assert.equal(tab.fold(), "open");
  assert.equal(tab.driver.state().leaving, false);
  tab.env.held = false;
  tab.driver.holdChanged();
  tab.tick(FOLD_LEAVE_MS - 1);
  assert.equal(tab.fold(), "open");
  tab.tick(1);
  assert.equal(tab.fold(), "rest");
  // Раскладку держит мышь, лежащая на «Создать», а фокус ушёл с поля клавишей.
  const hover = bench();
  hover.driver.pointerDown(1);
  hover.driver.pressedInside();
  hover.focusField();
  hover.driver.pointerUp(1);
  hover.env.held = true;
  hover.driver.holdChanged();
  hover.blur();
  hover.env.held = false;
  hover.driver.holdChanged();
  hover.tick(FOLD_LEAVE_MS);
  assert.equal(hover.fold(), "rest");
});

test("после ухода клавишей нажал в панели (Safari: фокус на кнопку не перешёл) — он снова в панели", () => {
  const b = typing();
  b.blur();
  b.driver.pointerDown(1);
  b.driver.pressedInside();
  b.driver.pointerUp(1);
  // Нажатие открыло окошко; закрылось оно само — человек никуда не уходил.
  b.env.held = true;
  b.driver.holdChanged();
  b.env.held = false;
  b.driver.holdChanged();
  b.tick(FOLD_LEAVE_MS * 4);
  assert.equal(b.fold(), "open");
  assert.equal(b.env.timers.length, 0);
});

test("окошко закрыли, выбрав значение: фокус вернулся на чип, нажатие было в окошке — это не уход", () => {
  // С клавиатуры: Enter в окошке, фокус возвращается на чип раньше, чем окошко исчезает.
  const keys = typing();
  keys.blur();
  keys.focusButton();
  keys.env.held = true;
  keys.driver.holdChanged();
  keys.env.held = false;
  keys.driver.holdChanged();
  keys.tick(FOLD_LEAVE_MS * 4);
  assert.equal(keys.fold(), "open");
  // Мышью в Safari: фокуса в панели нет, но нажатие было в окошке панели.
  const mouse = typing();
  mouse.env.held = true;
  mouse.driver.holdChanged();
  mouse.driver.pointerDown(1);
  mouse.driver.pressedInside();
  mouse.blur();
  mouse.driver.pointerUp(1);
  mouse.env.held = false;
  mouse.driver.holdChanged();
  mouse.tick(FOLD_LEAVE_MS * 4);
  assert.equal(mouse.fold(), "open");
  // Окошко закрылось, а шторка из стора ещё открыта — тоже не уход.
  const sheet = typing();
  sheet.blur();
  sheet.driver.setInputs({ fullscreen: false, overlay: true, problem: false });
  sheet.env.held = true;
  sheet.driver.holdChanged();
  sheet.env.held = false;
  sheet.driver.holdChanged();
  sheet.tick(FOLD_LEAVE_MS * 4);
  assert.equal(sheet.fold(), "open");
});

test("шторка из стора (параметры на телефоне): фокус и нажатия в ней — не уход ни до её открытия, ни после", () => {
  const b = typing();
  // Нажали чип параметров: фокус с поля ушёл, шторка открылась рендером позже.
  b.driver.pointerDown(1);
  b.driver.pressedInside();
  b.blur();
  b.driver.pointerUp(1);
  b.driver.setInputs({ fullscreen: false, overlay: true, problem: false });
  // В шторке (она вне дерева панели) нажимают и водят фокус.
  b.driver.pointerDown(2);
  b.driver.pointerUp(2);
  b.tick(FOLD_LEAVE_MS * 4);
  assert.equal(b.fold(), "open");
  assert.equal(b.driver.state().leaving, false);
  // Закрыли — поле остаётся развёрнутым до настоящего ухода.
  b.driver.setInputs({ fullscreen: false, overlay: false, problem: false });
  b.tick(FOLD_LEAVE_MS * 4);
  assert.equal(b.fold(), "open");
  b.driver.pointerDown(3);
  b.driver.pointerUp(3);
  b.tick(FOLD_LEAVE_MS);
  assert.equal(b.fold(), "rest");
});

test("шторка открылась уже после того, как фокус ушёл в неё: ожидание ухода снимается", () => {
  const b = typing();
  b.blur();
  assert.equal(b.driver.state().leaving, true);
  b.driver.setInputs({ fullscreen: false, overlay: true, problem: false });
  assert.equal(b.driver.state().leaving, false);
  b.driver.setInputs({ fullscreen: false, overlay: false, problem: false });
  b.tick(FOLD_LEAVE_MS * 4);
  assert.equal(b.fold(), "open");
});

test("во весь экран: уходить некуда, поле не сворачивается", () => {
  const b = typing();
  b.driver.setInputs({ fullscreen: true, overlay: false, problem: false });
  b.blur();
  b.tick(FOLD_LEAVE_MS * 4);
  assert.equal(b.fold(), "open");
});

test("набор через IME и выделенный текст держат поле; пауза идёт заново, когда они кончились", () => {
  const b = typing();
  b.driver.composition(true);
  b.blur();
  b.tick(FOLD_LEAVE_MS * 2);
  assert.equal(b.fold(), "open");
  b.driver.composition(false);
  b.env.selected = true;
  b.tick(FOLD_LEAVE_MS * 2);
  assert.equal(b.fold(), "open");
  b.env.selected = false;
  // selectionchange → nudge
  b.driver.nudge();
  b.tick(FOLD_LEAVE_MS);
  assert.equal(b.fold(), "rest");
});

test("чип тащат по лотку: поле ждёт конца перетаскивания", () => {
  const b = typing();
  b.driver.drag(true);
  b.blur();
  b.tick(FOLD_LEAVE_MS * 2);
  assert.equal(b.fold(), "open");
  b.driver.drag(false);
  b.tick(FOLD_LEAVE_MS);
  assert.equal(b.fold(), "rest");
});

test("окно потеряло фокус (другая вкладка, выбор файла) — это не уход из панели", () => {
  const b = typing();
  b.blur(false);
  b.tick(FOLD_LEAVE_MS * 10);
  assert.equal(b.fold(), "open");
  assert.equal(b.env.timers.length, 0);
  // Окно вернулось, фокус на прежнем месте — ничего не меняется.
  b.driver.windowFocus();
  b.tick(FOLD_LEAVE_MS * 2);
  assert.equal(b.fold(), "open");
});

test("окно вернулось, а фокус в панель — нет: теперь это уход", () => {
  const b = typing();
  b.blur(false);
  b.env.focus = false;
  b.driver.windowFocus();
  b.tick(FOLD_LEAVE_MS);
  assert.equal(b.fold(), "rest");
  // Второй раз то же событие ничего не делает.
  b.driver.windowFocus();
  assert.equal(b.env.timers.length, 0);
});

test("окно вернулось без фокуса в панели, а раскладка цены ещё висела: уход считается, когда она закрылась", () => {
  const b = bench();
  b.driver.pointerDown(1);
  b.driver.pressedInside();
  b.focusField();
  b.driver.pointerUp(1);
  b.env.held = true;
  b.driver.holdChanged();
  b.blur(false);
  b.env.focus = false;
  b.driver.windowFocus();
  assert.equal(b.driver.state().leaving, false);
  b.env.held = false;
  b.driver.holdChanged();
  b.tick(FOLD_LEAVE_MS);
  assert.equal(b.fold(), "rest");
});

test("кнопку мыши отпустили за окном: нажатие не остаётся «висеть»", () => {
  const b = bench();
  b.driver.pointerDown(1);
  b.driver.pressedInside();
  b.focusField();
  assert.equal(b.driver.state().waking, true);
  b.driver.windowBlur();
  assert.equal(b.fold(), "open");
  // Отпускание, которое всё же дошло, уже ничего не меняет.
  b.driver.pointerUp(1);
  assert.equal(b.fold(), "open");
});

test("правый клик в свёрнутый текст (macOS, Linux): отпускание забирает меню — поле разворачивается по самому меню", () => {
  const b = bench();
  // Номер указателя 0 — тоже номер: у мыши в Firefox он именно такой.
  b.driver.pointerDown(0, true);
  b.driver.pressedInside();
  b.focusField();
  assert.deepEqual(b.driver.state(), { fold: "rest", leaving: false, waking: true });
  // Отпускания не будет. Сами по себе ни пауза, ни «текст дорос до обрезки» поле не развернут.
  b.tick(FOLD_LEAVE_MS * 40);
  b.driver.open("field");
  assert.equal(b.fold(), "rest");
  b.driver.menu();
  assert.equal(b.fold(), "open");
  // Отпускание всё же дошло (меню отменил обработчик страницы) — второй раз оно не считается.
  b.driver.pointerUp(0);
  b.tick(FOLD_LEAVE_MS * 4);
  assert.equal(b.fold(), "open");
  assert.deepEqual(b.env.commits, ["open"]);
  assert.equal(b.env.timers.length, 0);
});

test("правый клик мимо панели: меню — конец нажатия, уход досчитывается", () => {
  const b = typing();
  b.driver.pointerDown(1, true);
  b.blur();
  // Нажатие «держится», пока страница не узнала о его конце.
  b.tick(FOLD_LEAVE_MS * 4);
  assert.equal(b.fold(), "open");
  b.driver.menu();
  b.tick(FOLD_LEAVE_MS - 1);
  assert.equal(b.fold(), "open");
  b.tick(1);
  assert.equal(b.fold(), "rest");
  assert.equal(b.env.timers.length, 0);
  // Safari: поле развёрнуто кнопкой, фокуса в панели нет и blur не придёт — уход узнаём по тому же меню.
  const s = bench();
  s.driver.toggle();
  s.driver.pointerDown(1, true);
  s.driver.menu();
  s.tick(FOLD_LEAVE_MS);
  assert.equal(s.fold(), "rest");
});

test("Windows: отпускание приходит раньше меню — меню ничего не меняет; палец меню не отпускает", () => {
  const b = typing();
  b.driver.pointerDown(1, true);
  b.driver.pressedInside();
  b.driver.pointerUp(1);
  const before = b.driver.state();
  b.driver.menu();
  assert.equal(b.driver.state(), before);
  assert.equal(b.env.timers.length, 0);
  // Долгое нажатие пальцем тоже зовёт меню, но палец ещё на экране: текст под ним не двигаем.
  const t = bench();
  t.driver.pointerDown(7);
  t.driver.pressedInside();
  t.focusField();
  t.driver.menu();
  assert.deepEqual(t.driver.state(), { fold: "rest", leaving: false, waking: true });
  t.driver.pointerUp(7);
  assert.equal(t.fold(), "open");
  // Мышью уже пользовались, а сейчас на странице палец: чужое нажатие меню не снимает.
  const mix = typing();
  mix.driver.pointerDown(1, true);
  mix.driver.pointerUp(1);
  mix.driver.pointerDown(7);
  mix.blur();
  mix.driver.menu();
  mix.tick(FOLD_LEAVE_MS * 4);
  assert.equal(mix.fold(), "open");
  mix.driver.pointerUp(7);
  mix.tick(FOLD_LEAVE_MS);
  assert.equal(mix.fold(), "rest");
});

test("в поле печатают под нажатием, которое так и не отпустили: поле разворачивается сразу", () => {
  const b = bench();
  b.driver.pointerDown(1, true);
  b.driver.pressedInside();
  b.focusField();
  assert.equal(b.fold(), "rest");
  b.driver.open("typed");
  assert.equal(b.fold(), "open");
  // Дальнейший ввод стор не дёргает.
  b.driver.open("typed");
  assert.deepEqual(b.env.commits, ["open"]);
});

test("проблема без человека в панели: поле развернулось и само свернулось, когда её исправили", () => {
  const b = bench();
  b.driver.setInputs({ fullscreen: false, overlay: false, problem: true });
  assert.equal(b.fold(), "open");
  b.tick(FOLD_LEAVE_MS * 4);
  assert.equal(b.fold(), "open");
  b.driver.setInputs({ fullscreen: false, overlay: false, problem: false });
  b.tick(FOLD_LEAVE_MS);
  assert.equal(b.fold(), "rest");
  assert.deepEqual(b.env.commits, ["open", "rest"]);
});

test("«мешает запуску» пропало дольше паузы и вернулось — поле свернулось бы и развернулось; с прошлым ответом стоит", () => {
  const inputs = (problem) => ({ fullscreen: false, overlay: false, problem });
  // Так было бы, если бы композер на время ожидания цены говорил «не мешает».
  const blink = bench();
  blink.driver.setInputs(inputs(true));
  blink.driver.setInputs(inputs(false));
  blink.tick(FOLD_LEAVE_MS);
  blink.driver.setInputs(inputs(true));
  assert.deepEqual(blink.env.commits, ["open", "rest", "open"]);
  // Композер держит прошлый ответ, пока новый в пути (lastKnown): поле не двигается.
  const b = bench();
  b.driver.setInputs(inputs(lastKnown(true, true, false)));
  b.driver.setInputs(inputs(lastKnown(false, false, true)));
  b.tick(FOLD_LEAVE_MS * 4);
  b.driver.setInputs(inputs(lastKnown(true, true, true)));
  assert.deepEqual(b.env.commits, ["open"]);
  // Ответ пришёл без ошибки — теперь оно сворачивается, через обычную паузу.
  b.driver.setInputs(inputs(lastKnown(true, false, true)));
  b.tick(FOLD_LEAVE_MS);
  assert.deepEqual(b.env.commits, ["open", "rest"]);
});

test("проблема при свёрнутом кнопкой поле его не разворачивает", () => {
  const b = bench("shut");
  b.driver.setInputs({ fullscreen: false, overlay: false, problem: true });
  assert.equal(b.fold(), "shut");
  assert.deepEqual(b.env.commits, []);
});

test("кнопка: свернуть сразу и без условий, показать — сразу; свёрнутое кнопкой уход не трогает", () => {
  const b = typing();
  b.env.held = true;
  b.env.selected = true;
  assert.equal(b.driver.toggle().fold, "shut");
  b.blur();
  b.tick(FOLD_LEAVE_MS * 4);
  assert.equal(b.fold(), "shut");
  assert.equal(b.env.timers.length, 0);
  assert.equal(b.driver.toggle().fold, "open");
  // Развёрнуто кнопкой и остаётся, пока человек не уйдёт из панели.
  b.env.held = false;
  b.env.selected = false;
  b.tick(FOLD_LEAVE_MS * 4);
  assert.equal(b.fold(), "open");
  b.driver.pointerDown(1);
  b.driver.pointerUp(1);
  b.tick(FOLD_LEAVE_MS);
  assert.equal(b.fold(), "rest");
});

test("запуск принят — поле сворачивается сразу; запуск с клавиатуры оставляет его развёрнутым", () => {
  const b = typing();
  b.blur();
  // Ответ водителя — убрать ли курсор из поля.
  assert.equal(b.driver.ran(false), true);
  assert.equal(b.fold(), "rest");
  assert.equal(b.env.timers.length, 0);
  const k = typing();
  assert.equal(k.driver.ran(true), false);
  assert.equal(k.fold(), "open");
});

test("ответ о запуске пришёл, пока в свёрнутом поле ещё нажата кнопка мыши: курсор остаётся, разворот — по отпусканию", () => {
  for (const from of ["rest", "shut"]) {
    const b = bench(from);
    b.driver.pointerDown(1, true);
    b.driver.pressedInside();
    b.focusField();
    // Человек вернулся к тексту — он пишет дальше. Поле при этом ещё не развёрнуто: по его виду
    // курсор убирать нельзя, только по typing.
    assert.equal(b.driver.ran(true), false, from);
    assert.deepEqual(b.driver.state(), { fold: from, leaving: false, waking: true }, from);
    b.driver.pointerUp(1);
    assert.equal(b.fold(), "open", from);
  }
});

test("текст снова помещается и новый проект: «свёрнуто кнопкой» становится обычным", () => {
  for (const how of ["fits", "reset"]) {
    const b = bench("shut");
    b.driver[how]();
    assert.equal(b.fold(), "rest", how);
    assert.deepEqual(b.env.commits, ["rest"], how);
  }
});

test("стор получает только настоящие смены состояния, а после dispose таймер не срабатывает", () => {
  const b = typing();
  b.focusField();
  b.focusButton();
  assert.deepEqual(b.env.commits, ["open"]);
  b.blur();
  b.driver.dispose();
  b.tick(FOLD_LEAVE_MS * 4);
  assert.equal(b.fold(), "open");
  assert.deepEqual(b.env.commits, ["open"]);
});
