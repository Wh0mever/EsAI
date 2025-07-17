from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings

def send_template_email(subject, template_name, context, recipient_list, from_email=None, attachments=None):
    """
    Отправка HTML-письма с шаблоном и возможностью прикрепления файлов.
    """
    from_email = from_email or settings.DEFAULT_FROM_EMAIL

    html_content = render_to_string(template_name, context)
    text_content = f"Your verification code is: {context.get('code')}"

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,  # plain text
        from_email=from_email,
        to=recipient_list,
    )
    msg.attach_alternative(html_content, "text/html")

    if attachments:
        for attachment in attachments:
            msg.attach(*attachment)

    msg.send()
