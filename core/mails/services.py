from typing import Iterable
from django.template import engines, Template
from django.conf import settings
from django.utils.html import strip_tags

from .models import EmailTemplate, EmailCampaign, EmailLog
from .sender import send_template_email  # твой готовый sender


def render_subject(subject: str, context: dict) -> str:
    return Template(subject).render(context)


def render_body_from_db_template(tpl: EmailTemplate, context: dict) -> tuple[str, str]:
    dj = engines["django"]
    html = dj.from_string(tpl.body_html).render(context)
    text = tpl.body_text.strip() or strip_tags(html)
    return html, text


def send_email_using_db_template(
    tpl: EmailTemplate,
    context: dict,
    recipients: Iterable[str],
    from_email: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
    campaign: EmailCampaign | None = None,
) -> int:
    subject = render_subject(tpl.subject, context)
    html, text = render_body_from_db_template(tpl, context)

    count = 0
    for to in recipients:
        try:
            send_template_email(
                subject=subject,
                raw_html=html,
                raw_text=text,
                context={},
                template_name=None,
                recipient_list=[to],
                from_email=from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None),
                attachments=attachments or [],
            )

        except Exception as e:
            EmailLog.objects.create(
                campaign=campaign, to_email=to, subject=subject, success=False, error=str(e), message_id=""
            )
        else:
            EmailLog.objects.create(
                campaign=campaign, to_email=to, subject=subject, success=True, error="", message_id=""
            )
            count += 1
    return count


def run_campaign_now(campaign: EmailCampaign) -> int:
    context = dict(campaign.context_json or {})
    tpl = campaign.template
    recipients = campaign.build_recipients()
    sent = send_email_using_db_template(
        tpl=tpl,
        context=context,
        recipients=recipients,
        from_email=campaign.from_email or None,
        attachments=None,
        campaign=campaign,
    )
    return sent
