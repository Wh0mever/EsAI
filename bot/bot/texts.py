"""Тексты бота на трёх языках.

Формулировки взяты с сайта (next/src/locales): человек не должен чувствовать,
что попал в другой продукт. Обращение на «вы», без канцелярита.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

TEXTS: dict[str, dict[str, str]] = {
    "ru": {
        "choose_lang": "Выберите язык · Choose language · Тилди тандаңыз",
        "lang_set": "Готово. Модели будут отвечать на русском.",
        "welcome": (
            "🎉 <b>Добро пожаловать в EsAI!</b>\n\n"
            "Здесь ChatGPT, Claude, Gemini, DeepSeek, картинки, видео и студия "
            "мультфильмов — в одном чате и с одним балансом.\n\n"
            "🎁 На ваш баланс начислено <b>{balance} кредитов</b>.\n"
            "Просто напишите вопрос — или выберите, с чего начать:"
        ),
        "welcome_back": (
            "С возвращением, {name} 👋\n"
            "Баланс: <b>{balance} кредитов</b> · модель: <b>{model}</b>\n"
            "Напишите вопрос или выберите действие."
        ),
        "from_referral": "Вы пришли по приглашению друга 🤝",
        "promo_ok": "🎟 Промокод активирован: <b>+{credits} кредитов</b>",
        "promo_fail": "Промокод не сработал: {reason}",
        "new_chat": "🆕 Новый чат. Модель: <b>{model}</b>. Напишите вопрос.",
        "thinking": "🤔 Думаю…",
        "drawing": "🎨 Рисую…",
        "answer_meta": "— {model} · {credits} кр · баланс {balance}",
        "busy": "⏳ Ещё отвечаю на предыдущий вопрос. Подождите пару секунд.",
        "failed": "😕 Не удалось получить ответ. Кредиты не списаны.",
        "server_down": "Сервер EsAI не отвечает. Попробуйте через минуту.",
        "blocked": "Доступ к аккаунту закрыт. Напишите в поддержку: /help",
        "not_allowed": (
            "Бот пока работает в тестовом режиме и отвечает только сотрудникам.\n"
            "Полная версия — на сайте esai.kg."
        ),
        # Пейволы — дословно как на сайте.
        "paywall_premium": (
            "🔒 <b>Премиум-модель доступна на платном тарифе</b>\n"
            "Пополните баланс, чтобы открыть все премиум-нейросети планеты."
        ),
        "paywall_balance": (
            "⚠️ <b>Недостаточно кредитов</b>\n"
            "На балансе {have} кредитов, для запроса нужно около {need}."
        ),
        "paywall_daily": (
            "⏳ <b>Достигнут дневной лимит запросов</b>\n"
            "Сегодня вы использовали все бесплатные запросы. "
            "Платный пакет снимает дневной лимит."
        ),
        "balance": (
            "💳 <b>Баланс: {balance} кредитов</b>\n"
            "Тариф: {tier}\n"
            "Кредиты не сгорают и работают везде: чат, картинки, видео и студия."
        ),
        "tier_free": "бесплатный",
        "tier_paid": "платный · все премиум-модели",
        "tier_unlimited": "безлимитный",
        "models_title": "🧠 Сейчас: <b>{model}</b>\nВыберите модель:",
        "model_set": "✅ Модель: <b>{model}</b>",
        "model_locked": "🔒 Эта модель доступна на платном тарифе.",
        "history_empty": "Пока ни одного чата. Напишите вопрос — и он появится здесь.",
        "history_title": "📜 <b>Ваши чаты</b>",
        "history_opened": "Открыт чат «{title}». Пишите.",
        "help": (
            "❓ <b>Как пользоваться</b>\n\n"
            "• Просто напишите вопрос — ответит выбранная модель\n"
            "• «Нарисуй …» или /image — картинка; /video — ролик; /studio — мультфильм\n"
            "• Пришлите PDF, Word, Excel, фото или голосовое — разберу\n"
            "• «Запомни …» — сохраню в память\n\n"
            "/model — модель · /new — новый чат · /balance — кредиты · /topup — пополнить\n"
            "/profile — профиль · /referral — пригласить · /help — эта справка\n\n"
            "Веб-версия: esai.kg — тот же аккаунт и тот же баланс."
        ),
        "file_too_big": (
            "Файл больше 20 МБ — Telegram не даёт ботам такие скачивать. "
            "Сожмите или разбейте на части."
        ),
        "file_too_big_api": "Максимальный размер файла для EsAI — 15 МБ.",
        "file_unsupported": "Пока понимаю PDF, Word, Excel, PowerPoint, TXT и фото.",
        "file_no_text": (
            "📄 Файл загружен, но текст из него не извлёкся — похоже, это скан. "
            "Пришлите PDF с текстом или фото страниц."
        ),
        "doc_ready": "📄 <b>{name}</b> загружен. Что с ним сделать?",
        "photo_ready": "🖼 Фото получено. Что сделать?",
        "voice_soon": "🎤 Голосовые пока не понимаю. Напишите, пожалуйста, текстом.",
        "no_vision": (
            "Модель <b>{model}</b> не понимает изображения. "
            "Выберите модель с пометкой «Фото» в /model."
        ),
        "btn_topup": "➕ Пополнить",
        "btn_free_model": "🆓 Бесплатная модель",
        "btn_retry": "🔁 Повторить",
        "btn_continue": "➡️ Продолжить",
        "btn_sources": "🌐 Источники",
        "btn_reasoning": "🧠 Ход рассуждений",
        "btn_back": "↩ Назад",
        "btn_close": "✖ Закрыть",
        "prefill_hint": "Допишите и отправьте.",
        "topup_hint": (
            "Пополнить баланс можно на сайте: {site}/pricing — карты, Элкарт, "
            "кошельки и криптовалюта. Аккаунт и баланс общие с ботом."
        ),
        "quick": {
            "article": "✍️ Статья",
            "image": "🎨 Картинка",
            "translate": "🌍 Перевод",
            "document": "📄 Документ",
            "code": "💻 Код",
            "study": "📊 Учёба",
            "travel": "✈️ Путешествие",
            "idea": "💡 Бизнес-идея",
        },
    },
    "en": {
        "choose_lang": "Выберите язык · Choose language · Тилди тандаңыз",
        "lang_set": "Done. The models will answer in English.",
        "welcome": (
            "🎉 <b>Welcome to EsAI!</b>\n\n"
            "ChatGPT, Claude, Gemini, DeepSeek, images, video and the cartoon "
            "studio — in one chat with one balance.\n\n"
            "🎁 <b>{balance} credits</b> have been added to your balance.\n"
            "Just type your question — or pick a starting point:"
        ),
        "welcome_back": (
            "Welcome back, {name} 👋\n"
            "Balance: <b>{balance} credits</b> · model: <b>{model}</b>\n"
            "Type your question or pick an action."
        ),
        "from_referral": "You came from a friend's invitation 🤝",
        "promo_ok": "🎟 Promo code applied: <b>+{credits} credits</b>",
        "promo_fail": "The promo code did not work: {reason}",
        "new_chat": "🆕 New chat. Model: <b>{model}</b>. Type your question.",
        "thinking": "🤔 Thinking…",
        "drawing": "🎨 Drawing…",
        "answer_meta": "— {model} · {credits} cr · balance {balance}",
        "busy": "⏳ Still answering your previous question. One moment.",
        "failed": "😕 Could not get an answer. No credits were charged.",
        "server_down": "EsAI is not responding. Please try again in a minute.",
        "blocked": "Your account is closed. Please contact support: /help",
        "not_allowed": (
            "The bot is in testing and answers staff only.\n"
            "The full version is at esai.kg."
        ),
        "paywall_premium": (
            "🔒 <b>Premium models require a paid plan</b>\n"
            "Top up your balance to unlock every premium model."
        ),
        "paywall_balance": (
            "⚠️ <b>Not enough credits</b>\n"
            "You have {have} credits, this request needs about {need}."
        ),
        "paywall_daily": (
            "⏳ <b>Daily request limit reached</b>\n"
            "You have used all free requests for today."
        ),
        "balance": (
            "💳 <b>Balance: {balance} credits</b>\n"
            "Plan: {tier}\n"
            "Credits never expire and work everywhere: chat, images, video, studio."
        ),
        "tier_free": "free",
        "tier_paid": "paid · all premium models",
        "tier_unlimited": "unlimited",
        "models_title": "🧠 Current: <b>{model}</b>\nPick a model:",
        "model_set": "✅ Model: <b>{model}</b>",
        "model_locked": "🔒 This model requires a paid plan.",
        "history_empty": "No chats yet. Ask something and it will appear here.",
        "history_title": "📜 <b>Your chats</b>",
        "history_opened": "Chat «{title}» is open. Go ahead.",
        "help": (
            "❓ <b>How to use</b>\n\n"
            "• Just type a question — the selected model answers\n"
            "• “Draw …” or /image — a picture; /video — a clip; /studio — a cartoon\n"
            "• Send a PDF, Word, Excel, photo or voice message — I will handle it\n"
            "• “Remember …” — saved to memory\n\n"
            "/model — model · /new — new chat · /balance — credits · /topup — top up\n"
            "/profile — profile · /referral — invite · /help — this help\n\n"
            "Web version: esai.kg — same account, same balance."
        ),
        "file_too_big": "Files over 20 MB cannot be downloaded by bots in Telegram.",
        "file_too_big_api": "The maximum file size for EsAI is 15 MB.",
        "file_unsupported": "I understand PDF, Word, Excel, PowerPoint, TXT and photos.",
        "file_no_text": "📄 The file is uploaded but no text was extracted — looks like a scan.",
        "doc_ready": "📄 <b>{name}</b> uploaded. What should I do with it?",
        "photo_ready": "🖼 Photo received. What should I do?",
        "voice_soon": "🎤 I cannot understand voice messages yet. Please type instead.",
        "no_vision": "The model <b>{model}</b> cannot read images. Pick one marked «Photo» in /model.",
        "btn_topup": "➕ Top up",
        "btn_free_model": "🆓 Free model",
        "btn_retry": "🔁 Retry",
        "btn_continue": "➡️ Continue",
        "btn_sources": "🌐 Sources",
        "btn_reasoning": "🧠 Reasoning",
        "btn_back": "↩ Back",
        "btn_close": "✖ Close",
        "prefill_hint": "Finish the sentence and send it.",
        "topup_hint": (
            "You can top up at {site}/pricing — cards, Elcart, wallets and crypto. "
            "The account and balance are shared with the bot."
        ),
        "quick": {
            "article": "✍️ Article",
            "image": "🎨 Image",
            "translate": "🌍 Translate",
            "document": "📄 Document",
            "code": "💻 Code",
            "study": "📊 Studying",
            "travel": "✈️ Trip",
            "idea": "💡 Business idea",
        },
    },
    "kg": {
        "choose_lang": "Выберите язык · Choose language · Тилди тандаңыз",
        "lang_set": "Даяр. Моделдер кыргызча жооп берет.",
        "welcome": (
            "🎉 <b>EsAI'ге кош келиңиз!</b>\n\n"
            "ChatGPT, Claude, Gemini, DeepSeek, сүрөттөр, видео жана мультфильм "
            "студиясы — бир чатта, бир баланс менен.\n\n"
            "🎁 Балансыңызга <b>{balance} кредит</b> кошулду.\n"
            "Суроону жазыңыз — же эмнеден баштоону тандаңыз:"
        ),
        "welcome_back": (
            "Кайра кош келиңиз, {name} 👋\n"
            "Баланс: <b>{balance} кредит</b> · модель: <b>{model}</b>\n"
            "Суроо жазыңыз же аракет тандаңыз."
        ),
        "from_referral": "Сиз досуңуздун чакыруусу менен келдиңиз 🤝",
        "promo_ok": "🎟 Промокод иштеди: <b>+{credits} кредит</b>",
        "promo_fail": "Промокод иштеген жок: {reason}",
        "new_chat": "🆕 Жаңы чат. Модель: <b>{model}</b>. Суроону жазыңыз.",
        "thinking": "🤔 Ойлонуп жатам…",
        "drawing": "🎨 Тартып жатам…",
        "answer_meta": "— {model} · {credits} кр · баланс {balance}",
        "busy": "⏳ Мурунку сурооңузга жооп берип жатам. Бир аз күтө туруңуз.",
        "failed": "😕 Жооп алынган жок. Кредиттер алынган жок.",
        "server_down": "EsAI жооп бербей жатат. Бир мүнөттөн кийин аракет кылыңыз.",
        "blocked": "Аккаунтка кирүү жабык. Колдоого жазыңыз: /help",
        "not_allowed": (
            "Бот сынак режиминде иштеп жатат жана кызматкерлерге гана жооп берет.\n"
            "Толук версия: esai.kg."
        ),
        "paywall_premium": (
            "🔒 <b>Премиум модель акылуу пакетте жеткиликтүү</b>\n"
            "Бардык премиум моделдерди ачуу үчүн балансты толтуруңуз."
        ),
        "paywall_balance": (
            "⚠️ <b>Кредит жетишсиз</b>\n"
            "Балансыңызда {have} кредит, сурооgo болжол менен {need} керек."
        ),
        "paywall_daily": (
            "⏳ <b>Күндүк чек жетти</b>\n"
            "Бүгүн бардык акысыз суроолорду колдондуңуз."
        ),
        "balance": (
            "💳 <b>Баланс: {balance} кредит</b>\n"
            "Тариф: {tier}\n"
            "Кредиттер күйбөйт жана бардык жерде иштейт: чат, сүрөт, видео, студия."
        ),
        "tier_free": "акысыз",
        "tier_paid": "акылуу · бардык премиум моделдер",
        "tier_unlimited": "чексиз",
        "models_title": "🧠 Учурда: <b>{model}</b>\nМодель тандаңыз:",
        "model_set": "✅ Модель: <b>{model}</b>",
        "model_locked": "🔒 Бул модель акылуу пакетте жеткиликтүү.",
        "history_empty": "Азырынча чат жок. Суроо жазыңыз — ушул жерде пайда болот.",
        "history_title": "📜 <b>Сиздин чаттар</b>",
        "history_opened": "«{title}» чаты ачылды. Жаза бериңиз.",
        "help": (
            "❓ <b>Кантип колдонуу</b>\n\n"
            "• Жөн гана суроо жазыңыз — тандалган модель жооп берет\n"
            "• «Тарт …» же /image — сүрөт; /video — ролик; /studio — мультфильм\n"
            "• PDF, Word, Excel, сүрөт же үн билдирүү жөнөтүңүз\n"
            "• «Эстеп кал …» — эске сактайм\n\n"
            "/model — модель · /new — жаңы чат · /balance — кредиттер · /topup — толуктоо\n"
            "/profile — профиль · /referral — чакыруу · /help — бул жардам\n\n"
            "Веб-версия: esai.kg — ошол эле аккаунт жана баланс."
        ),
        "file_too_big": "20 МБ ашкан файлды Telegram боттордун жүктөөсүнө уруксат бербейт.",
        "file_too_big_api": "EsAI үчүн файлдын эң чоң өлчөмү — 15 МБ.",
        "file_unsupported": "Азырынча PDF, Word, Excel, PowerPoint, TXT жана сүрөттөрдү түшүнөм.",
        "file_no_text": "📄 Файл жүктөлдү, бирок андан текст чыккан жок — сканга окшойт.",
        "doc_ready": "📄 <b>{name}</b> жүктөлдү. Аны эмне кылалы?",
        "photo_ready": "🖼 Сүрөт келди. Эмне кылалы?",
        "voice_soon": "🎤 Үн билдирүүлөрүн азырынча түшүнбөйм. Текст менен жазыңыз.",
        "no_vision": "<b>{model}</b> модели сүрөттөрдү түшүнбөйт. /model'ден «Фото» белгиси барын тандаңыз.",
        "btn_topup": "➕ Толуктоо",
        "btn_free_model": "🆓 Акысыз модель",
        "btn_retry": "🔁 Кайталоо",
        "btn_continue": "➡️ Улантуу",
        "btn_sources": "🌐 Булактар",
        "btn_reasoning": "🧠 Ой жүгүртүү",
        "btn_back": "↩ Артка",
        "btn_close": "✖ Жабуу",
        "prefill_hint": "Толуктап, жөнөтүңүз.",
        "topup_hint": (
            "Балансты сайттан толуктаса болот: {site}/pricing — карталар, Элкарт, "
            "капчыктар жана криптовалюта. Аккаунт жана баланс бот менен бирдей."
        ),
        "quick": {
            "article": "✍️ Макала",
            "image": "🎨 Сүрөт",
            "translate": "🌍 Котормо",
            "document": "📄 Документ",
            "code": "💻 Код",
            "study": "📊 Окуу",
            "travel": "✈️ Саякат",
            "idea": "💡 Бизнес идея",
        },
    },
}

# Промпты быстрых кнопок — те же, что на стартовом экране сайта.
QUICK_PROMPTS: dict[str, dict[str, str]] = {
    "ru": {
        "article": "Напиши статью на тему: ",
        "image": "Нарисуй ",
        "translate": "Переведи на русский язык этот текст: ",
        "document": "Кратко перескажи этот документ: ",
        "code": "Напиши код, который ",
        "study": "Объясни простыми словами тему: ",
        "travel": "Составь план путешествия в ",
        "idea": "Придумай бизнес-идею в сфере ",
    },
    "en": {
        "article": "Write an article about: ",
        "image": "Draw ",
        "translate": "Translate this text into English: ",
        "document": "Summarise this document: ",
        "code": "Write code that ",
        "study": "Explain in simple words: ",
        "travel": "Plan a trip to ",
        "idea": "Suggest a business idea in ",
    },
    "kg": {
        "article": "Ушул тема боюнча макала жаз: ",
        "image": "Тарт: ",
        "translate": "Бул текстти кыргызчага которуп бер: ",
        "document": "Бул документти кыскача айтып бер: ",
        "code": "Код жаз: ",
        "study": "Жөнөкөй сөз менен түшүндүр: ",
        "travel": "Саякат планын түз: ",
        "idea": "Бизнес идея сунушта: ",
    },
}


# Ключи, объявленные здесь, — общие для всего бота. Снимок делается при
# загрузке модуля, до того как экраны досыпят свои тексты.
BASE_KEYS = frozenset(TEXTS["ru"])


def register_texts(extra: dict[str, dict[str, str]]) -> None:
    """Досыпать тексты из другого модуля.

    Каждый экран держит свои строки у себя и регистрирует их при импорте —
    так один общий словарь не превращается в файл, который правят все сразу.

    Общие ключи экран перебить не может: однажды «История операций» из экрана
    оплаты подменила собой заголовок списка чатов, и человек в /history видел
    чужую подпись. Такой ключ игнорируется с записью в лог — экрану нужно своё
    имя (например tx_history_title).
    """
    for lang, bundle in (extra or {}).items():
        target = TEXTS.setdefault(lang, {})
        for key, value in (bundle or {}).items():
            if key in BASE_KEYS:
                logger.warning("текст %r уже общий — экран не может его переопределить", key)
                continue
            target[key] = value


def t(lang: str, key: str, **kwargs) -> str:
    """Текст на языке человека; если перевода нет — по-русски."""
    bundle = TEXTS.get(lang) or TEXTS["ru"]
    value = bundle.get(key)
    if value is None:
        value = TEXTS["ru"].get(key, key)
    if kwargs and isinstance(value, str):
        try:
            return value.format(**kwargs)
        except (KeyError, IndexError):
            return value
    return value


def quick_label(lang: str, key: str) -> str:
    bundle = (TEXTS.get(lang) or TEXTS["ru"]).get("quick", {})
    return bundle.get(key) or TEXTS["ru"]["quick"].get(key, key)


def quick_prompt(lang: str, key: str) -> str:
    bundle = QUICK_PROMPTS.get(lang) or QUICK_PROMPTS["ru"]
    return bundle.get(key) or QUICK_PROMPTS["ru"].get(key, "")
