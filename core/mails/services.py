from typing import Iterable
from django.conf import settings
from .sender import send_template_email
from .models import MailContext, SimpleMail


# --- Simple helper to send branded emails via common.html ---
## legacy helpers removed; using simplified renderer below


# ===== Simplified renderer =====

def _render_lines_from_context(data: dict) -> str:
    """Render HTML blocks from dict preserving key order.

    Rules:
      - key contains 'title' => <h2>
      - key contains 'link'  => value = {href, text} => <p><a>
      - key contains 'list'  => value iterable or object => <ul><li>
      - else => <p>value</p>
    """
    if not isinstance(data, dict):
        return ""
    parts: list[str] = []
    for k, v in data.items():
        k_low = str(k).lower()
        if "title" in k_low:
            parts.append(f"<h2 style='margin:16px 0 6px;font-size:20px;color:#111;font-weight:700'>{v}</h2>")
        elif "link" in k_low:
            href = "#"; text = str(v)
            if isinstance(v, dict):
                href = v.get("href") or "#"
                text = v.get("text") or href
            parts.append(
                f"<p style='margin:8px 0'><a href='{href}' style='color:#2563eb;text-decoration:underline'>{text}</a></p>"
            )
        elif "list" in k_low:
            items: list[str] = []
            if isinstance(v, (list, tuple)):
                items = [str(x) for x in v]
            elif isinstance(v, dict):
                items = [str(x) for x in v.values()]
            if items:
                li = "".join([f"<li style='margin:4px 0'>{x}</li>" for x in items])
                parts.append(f"<ul style='padding-left:18px;margin:8px 0'>{li}</ul>")
        else:
            parts.append(f"<p style='margin:8px 0'>{v}</p>")
    return "\n".join(parts)


def render_simple_mail_html(mail: SimpleMail) -> str:
    ctx = mail.context.data if mail.context else {}
    content = _render_lines_from_context(ctx)
    # wrap minimal frame with logo
    company = getattr(settings, "SITE_NAME", "Vokalo")
    # Try to build absolute logo URL so Gmail/clients can fetch it
    static_url = getattr(settings, "STATIC_URL", "/static/") or "/static/"
    base_url = getattr(settings, "SITE_BASE_URL", "") or getattr(settings, "PUBLIC_BASE_URL", "")
    if base_url and not static_url.startswith("http"):
        base = base_url[:-1] if base_url.endswith("/") else base_url
        logo = f"{base}{static_url}img/base.png"
    else:
        # fallback to relative; some clients may hide it
        logo = f"{static_url}img/base.png"
    html = f"""
    <div style='max-width:600px;margin:24px auto;background:#ffffff;border-radius:8px;padding:20px;border:1px solid #eee'>
      <div style='text-align:center;margin-bottom:12px'>
        <img src='{logo}' alt='{company}' style='height:40px;max-width:180px;object-fit:contain' />
      </div>
      {content}
    </div>
    """
    return html


def send_simple_mail(mail: SimpleMail, *, test_to: str | None = None) -> int:
    subject = mail.subject
    html = render_simple_mail_html(mail)
    recipients: list[str]
    if test_to:
        recipients = [test_to]
    else:
        recipients = mail.build_recipients()
    sent = 0
    for to in recipients:
        try:
            send_template_email(
                subject=subject,
                raw_html=html,
                raw_text=None,
                context={},
                template_name=None,
                recipient_list=[to],
                from_email=None,
                attachments=None,
            )
            sent += 1
        except Exception:
            continue
    return sent
