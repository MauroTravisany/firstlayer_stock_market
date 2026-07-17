import requests


DISCORD_CONTENT_LIMIT = 2000
SLACK_TEXT_LIMIT = 12000


def _detect_webhook_type(config):
    webhook_type = config.get("alert_webhook_type") or "auto"
    url = config.get("alert_webhook_url") or ""
    if webhook_type != "auto":
        return webhook_type
    if "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url:
        return "discord"
    return "slack"


def build_alert_text(summary):
    return (
        f"*{summary['alert_title']}*\n\n"
        f"{summary['portfolio_summary']}\n\n"
        f"*Oportunidades*\n{summary['top_opportunities']}\n\n"
        f"*Sobrevaloradas*\n{summary['overvalued_summary']}\n\n"
        f"*Riesgos*\n{summary['risk_summary']}"
    )


def _truncate_text(text, limit):
    if len(text) <= limit:
        return text
    suffix = "\n\n[Mensaje truncado. Ver detalle completo en Looker Studio / BigQuery.]"
    return text[: max(0, limit - len(suffix))].rstrip() + suffix


def send_webhook_alert(config, summary):
    url = config.get("alert_webhook_url")
    if not url:
        return False, "ALERT_WEBHOOK_URL not configured"

    text = build_alert_text(summary)
    webhook_type = _detect_webhook_type(config)
    if webhook_type == "discord":
        payload = {"content": _truncate_text(text, DISCORD_CONTENT_LIMIT)}
    else:
        payload = {"text": _truncate_text(text, SLACK_TEXT_LIMIT)}

    response = requests.post(url, json=payload, timeout=30)
    if response.status_code >= 300:
        return False, f"Webhook error {response.status_code}: {response.text}"
    return True, None
