"""Настройки бота. Берутся из того же .env, что и сайт."""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- Telegram ---
    # Токен ТОВАРНОГО бота. У входа на сайт свой бот и свой токен: это разные
    # боты, но id пользователя в Telegram один на все — аккаунт остаётся общим.
    bot_token: str = Field("", alias="TELEGRAM_PRODUCT_BOT_TOKEN")
    bot_username: str = Field("", alias="TELEGRAM_PRODUCT_BOT_USERNAME")

    # --- Наш API ---
    # Ходим прямо в контейнер core, минуя nginx: в docker-сети это дешевле и
    # не зависит от сертификатов.
    api_base: str = Field("http://core:8000", alias="BOT_API_BASE")
    # Хост, которым представляемся: по нему core строит ссылки на /media/,
    # а по ним OpenRouter забирает картинки. Внутренний адрес там не годится.
    public_host: str = Field("esai.kg", alias="BOT_PUBLIC_HOST")
    site_base_url: str = Field("https://esai.kg", alias="SITE_BASE_URL")
    service_secret: str = Field("", alias="BOT_SERVICE_SECRET")

    # --- Инфраструктура ---
    redis_url: str = Field("redis://redis:6379/3", alias="BOT_REDIS_URL")
    mode: str = Field("polling", alias="BOT_MODE")
    webhook_secret: str = Field("", alias="BOT_WEBHOOK_SECRET")
    webhook_path: str = Field("/tg-webhook/", alias="BOT_WEBHOOK_PATH")
    webhook_port: int = Field(8081, alias="BOT_WEBHOOK_PORT")
    webhook_base: str = Field("", alias="BOT_WEBHOOK_BASE")

    # --- Доступ ---
    # staff — бот отвечает только своим (обкатка на проде), all — всем.
    access: str = Field("staff", alias="BOT_ACCESS")
    staff_ids: str = Field("", alias="BOT_STAFF_IDS")

    # --- Поведение ---
    default_model: str = Field("google/gemini-2.5-flash", alias="BOT_DEFAULT_MODEL")
    # Живой человек для случаев, когда бот молчит или аккаунт закрыт: кнопка
    # «Написать» появляется только если адрес задан (SUPPORT_URL=https://t.me/...).
    support_url: str = Field("", alias="SUPPORT_URL")
    log_level: str = Field("INFO", alias="BOT_LOG_LEVEL")
    log_file: str = Field("/app/logs/bot.log", alias="BOT_LOG_FILE")
    alive_file: str = Field("/tmp/bot.alive", alias="BOT_ALIVE_FILE")

    @property
    def staff(self) -> set[int]:
        out = set()
        for chunk in (self.staff_ids or "").replace(";", ",").split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                out.add(int(chunk))
        return out

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.service_secret)

    def allowed(self, telegram_id: int) -> bool:
        if (self.access or "").lower() == "all":
            return True
        return int(telegram_id) in self.staff


settings = Settings()
