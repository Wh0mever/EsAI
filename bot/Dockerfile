FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY bot/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY bot/bot /app/bot

# Бот ничего не пишет на диск, кроме логов, и не должен работать от root.
RUN useradd --create-home --uid 1000 botuser && mkdir -p /app/logs && chown -R botuser /app
USER botuser

# Пульс: воркер трогает файл, docker считает бота живым, пока он свежий.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,time,sys; p='/tmp/bot.alive'; sys.exit(0 if os.path.exists(p) and time.time()-os.path.getmtime(p) < 90 else 1)"

CMD ["python", "-m", "bot"]
