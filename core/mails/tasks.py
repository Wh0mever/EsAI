from core.celery import app
from .models import SimpleMail
from .services import send_simple_mail


@app.task(name="mails.send_simple_mail")
def send_simple_mail_task(mail_id: int, test_to: str | None = None) -> int:
    try:
        mail = SimpleMail.objects.get(pk=mail_id)
    except SimpleMail.DoesNotExist:
        return 0
    return send_simple_mail(mail, test_to=test_to)

