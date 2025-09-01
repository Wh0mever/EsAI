from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings

def send_template_email(
    subject,
    template_name=None,
    context=None,
    recipient_list=None,
    from_email=None,
    attachments=None,
    raw_html: str | None = None,
    raw_text: str | None = None,
):
    """
    Either render from template_name or use raw_html/raw_text.
    """
    context = context or {}
    from_email = from_email or settings.DEFAULT_FROM_EMAIL
    recipient_list = recipient_list or []

    if raw_html is not None:
        html_content = raw_html
        text_content = raw_text or " "
    else:
        html_content = render_to_string(template_name, context or {})
        text_content = raw_text or f"Your verification code is: {context.get('code', '')}"

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=from_email,
        to=recipient_list,
    )
    msg.attach_alternative(html_content, "text/html")

    if attachments:
        for attachment in attachments:
            msg.attach(*attachment)

    msg.send()
