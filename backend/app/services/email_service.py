# app/services/email_service.py
"""
SMTP email delivery for automation reports.
Vendor-neutral — works with Resend, Postmark, Sendgrid, Mailgun, Gmail, …
"""

from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib
from jinja2 import Template

from app.config import get_settings

logger = logging.getLogger(__name__)


# Simple, self-contained HTML template — no external dependencies.
#
# When `show_final` is true (format is "merge" or "template"), the composed
# `final_output` is shown as the primary body and per-step details are
# collapsed behind a <details> disclosure. When false (default/legacy
# "last_step"), we list per-step sections as before.
_HTML_TEMPLATE = Template("""\
<!doctype html>
<html lang="de">
  <head><meta charset="utf-8"></head>
  <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 720px; margin: 0 auto; padding: 24px; color: #111; background: #fff;">
    <div style="border-bottom: 1px solid #e5e7eb; padding-bottom: 12px; margin-bottom: 24px;">
      <h1 style="margin: 0; font-size: 20px;">{{ automation.name }}</h1>
      {% if automation.description %}
      <p style="margin: 4px 0 0; font-size: 13px; color: #6b7280;">{{ automation.description }}</p>
      {% endif %}
    </div>

    <div style="font-size: 13px; color: #6b7280; margin-bottom: 20px;">
      Ausgeführt am {{ started_at }} · {{ step_count }} Schritt{{ 'e' if step_count != 1 else '' }}
      {% if run.trigger == 'schedule' %} · Zeitplan{% else %} · Manuell{% endif %}
    </div>

    {% if show_final and run.final_output %}
    <section style="margin-bottom: 28px; padding: 20px; border: 1px solid #e5e7eb; border-radius: 8px; background: #fafafa;">
      <div style="white-space: pre-wrap; font-size: 14px; line-height: 1.6;">{{ run.final_output }}</div>
    </section>

    <details style="margin-bottom: 28px;">
      <summary style="cursor: pointer; font-size: 13px; color: #6b7280;">Details je Schritt anzeigen</summary>
      <div style="margin-top: 16px;">
        {% for step in run.step_results %}
        <section style="margin-bottom: 16px; padding: 12px; border: 1px solid #e5e7eb; border-radius: 6px; background: #fafafa;">
          <header style="margin-bottom: 8px;">
            <span style="display:inline-block; background:#eef2ff; color:#4338ca; font-size:11px; padding:2px 8px; border-radius:12px; margin-right:6px;">Schritt {{ step.order }}</span>
            <strong style="font-size: 13px;">{{ step.name }}</strong>
            <span style="font-size: 11px; color: #6b7280; margin-left: 6px;">· {{ step.repo }}</span>
          </header>
          {% if step.error %}
          <div style="background: #fef2f2; color: #991b1b; padding: 8px 12px; border-radius: 4px; font-size: 12px;">
            Fehler: {{ step.error }}
          </div>
          {% else %}
          <div style="white-space: pre-wrap; font-size: 13px; line-height: 1.5; color: #374151;">{{ step.output }}</div>
          {% endif %}
        </section>
        {% endfor %}
      </div>
    </details>
    {% else %}
    {% for step in run.step_results %}
    <section style="margin-bottom: 28px; padding: 16px; border: 1px solid #e5e7eb; border-radius: 8px; background: #fafafa;">
      <header style="margin-bottom: 10px;">
        <span style="display:inline-block; background:#eef2ff; color:#4338ca; font-size:11px; padding:2px 8px; border-radius:12px; margin-right:6px;">Schritt {{ step.order }}</span>
        <strong style="font-size: 14px;">{{ step.name }}</strong>
        <span style="font-size: 11px; color: #6b7280; margin-left: 6px;">· {{ step.repo }}</span>
      </header>
      {% if step.error %}
      <div style="background: #fef2f2; color: #991b1b; padding: 8px 12px; border-radius: 4px; font-size: 13px;">
        Fehler: {{ step.error }}
      </div>
      {% else %}
      <div style="white-space: pre-wrap; font-size: 14px; line-height: 1.55;">{{ step.output }}</div>
      {% endif %}
    </section>
    {% endfor %}
    {% endif %}

    <footer style="margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #9ca3af;">
      GitHub Reporter · Automation <code>{{ automation.automation_id }}</code>
    </footer>
  </body>
</html>
""")


_TEXT_TEMPLATE = Template("""\
{{ automation.name }}
{{ '=' * (automation.name | length) }}

{% if automation.description %}{{ automation.description }}

{% endif %}Ausgeführt am {{ started_at }} ({{ step_count }} Schritt{{ 'e' if step_count != 1 else '' }})

{% if show_final and run.final_output %}
{{ run.final_output }}

-- Details je Schritt --
{% endif %}{% for step in run.step_results %}
--- Schritt {{ step.order }}: {{ step.name }} ({{ step.repo }}) ---
{% if step.error %}FEHLER: {{ step.error }}{% else %}{{ step.output }}{% endif %}

{% endfor %}
""")


def is_configured() -> bool:
    """True if SMTP has minimum config to attempt sending."""
    s = get_settings()
    return bool(s.smtp_host and s.smtp_from)


async def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> None:
    """Send an email via the configured SMTP server. Raises on failure."""
    settings = get_settings()
    if not settings.smtp_host:
        raise RuntimeError("SMTP_HOST nicht konfiguriert — E-Mail kann nicht gesendet werden.")
    if not settings.smtp_from:
        raise RuntimeError("SMTP_FROM nicht konfiguriert — E-Mail kann nicht gesendet werden.")

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    # aiosmtplib picks TLS mode:
    #   use_tls=True  -> implicit TLS (port 465)
    #   start_tls=True -> STARTTLS (port 587, common)
    if settings.smtp_use_ssl:
        use_tls = True
        start_tls = False
    else:
        use_tls = False
        start_tls = settings.smtp_use_tls

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        use_tls=use_tls,
        start_tls=start_tls,
    )
    logger.info("Email sent to %s: %s", to_email, subject)


async def send_automation_report(
    to_email: str,
    automation: dict,
    run: dict,
) -> None:
    """Render + send the automation run report."""
    fmt = automation.get("final_output_format") or "last_step"
    ctx = {
        "automation": automation,
        "run": run,
        "step_count": len(run.get("step_results", [])),
        "started_at": str(run.get("started_at", ""))[:19].replace("T", " "),
        # Show the composed final_output as the hero section whenever the
        # user opted into an explicit format.
        "show_final": fmt in ("merge", "template"),
    }
    html_body = _HTML_TEMPLATE.render(**ctx)
    text_body = _TEXT_TEMPLATE.render(**ctx)
    subject = f"[GitHub Reporter] {automation.get('name', 'Automation')}"
    await send_email(
        to_email=to_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )
