import requests


DISCORD_CONTENT_LIMIT = 2000
DISCORD_FIELD_LIMIT = 650
DISCORD_MAX_FIELDS_PER_SECTION = 5
SLACK_TEXT_LIMIT = 12000
DEFAULT_MIN_FINAL_SCORE = 6.0
DEFAULT_MIN_CONFIDENCE = 0.65
DEFAULT_MIN_SELL_SCORE = 7.0
DEFAULT_MIN_MARGIN_OF_SAFETY = 0.08
MAX_BUY_FORWARD_PE = 28
MAX_BUY_PE = 35
MAX_BUY_PRICE_TO_SALES = 6
MAX_BUY_EV_TO_EBITDA = 22
DISCORD_GREEN = 0x2ECC71
DISCORD_RED = 0xE74C3C
DISCORD_GOLD = 0xF1C40F
DISCORD_BLUE = 0x3498DB


def _detect_webhook_type(config):
    webhook_type = config.get("alert_webhook_type") or "auto"
    url = config.get("alert_webhook_url") or ""
    if webhook_type != "auto":
        return webhook_type
    if "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url:
        return "discord"
    return "slack"


def clear_opportunity_rows(analysis_rows, min_final_score=DEFAULT_MIN_FINAL_SCORE, min_confidence=DEFAULT_MIN_CONFIDENCE):
    rows = []
    for row in analysis_rows:
        if row.get("signal") != "COMPRAR_OBSERVAR":
            continue
        final_score = row.get("final_score")
        confidence_score = row.get("confidence_score")
        if final_score is None or float(final_score) < min_final_score:
            continue
        if confidence_score is None or float(confidence_score) < min_confidence:
            continue
        if row.get("ai_final_alert_action") and row.get("ai_final_alert_action") != "ENVIAR_COMPRA":
            continue
        if row.get("ai_signal_agreement") == "CONTRADICE_MODELO":
            continue
        if row.get("ai_valuation_opinion") == "CARA":
            continue
        if row.get("missing_data_impact") == "ALTO":
            continue
        if not _passes_buy_valuation_guardrails(row):
            continue
        rows.append(row)
    return sorted(rows, key=lambda item: item.get("final_score") or 0, reverse=True)


def observe_opportunity_rows(analysis_rows, clear_rows=None, min_final_score=DEFAULT_MIN_FINAL_SCORE):
    clear_tickers = {row.get("ticker") for row in (clear_rows or [])}
    rows = []
    for row in analysis_rows:
        if row.get("ticker") in clear_tickers:
            continue
        if row.get("signal") != "COMPRAR_OBSERVAR":
            continue
        final_score = row.get("final_score")
        if final_score is None or float(final_score) < min_final_score:
            continue
        if row.get("missing_data_impact") == "ALTO":
            continue
        if row.get("ai_valuation_opinion") == "CARA":
            continue
        rows.append(row)
    return sorted(rows, key=lambda item: item.get("final_score") or 0, reverse=True)


def clear_sell_rows(analysis_rows, min_sell_score=DEFAULT_MIN_SELL_SCORE, min_confidence=DEFAULT_MIN_CONFIDENCE):
    rows = []
    for row in analysis_rows:
        if row.get("sell_signal") != "VENTA_CLARA" and row.get("signal") != "VENDER_OBSERVAR":
            continue
        sell_score = row.get("sell_score")
        confidence_score = row.get("confidence_score")
        if sell_score is None or float(sell_score) < min_sell_score:
            continue
        if confidence_score is None or float(confidence_score) < min_confidence:
            continue
        if row.get("ai_final_alert_action") and row.get("ai_final_alert_action") != "ENVIAR_VENTA":
            continue
        rows.append(row)
    return sorted(rows, key=lambda item: item.get("sell_score") or 0, reverse=True)


def _normalized_confidence(value):
    if value is None:
        return 0.0
    confidence = float(value)
    if confidence > 1:
        return confidence / 100
    return confidence


def _float_or_none(value):
    if value is None:
        return None
    return float(value)


def _passes_buy_valuation_guardrails(row):
    valuation_score = _float_or_none(row.get("valuation_score"))
    if valuation_score is None or valuation_score < 2:
        return False
    margin_of_safety = _float_or_none(row.get("margin_of_safety_pct"))
    if margin_of_safety is None or margin_of_safety < DEFAULT_MIN_MARGIN_OF_SAFETY:
        return False

    pe_ratio = _float_or_none(row.get("pe_ratio"))
    forward_pe = _float_or_none(row.get("forward_pe"))
    price_to_sales = _float_or_none(row.get("price_to_sales"))
    ev_to_ebitda = _float_or_none(row.get("ev_to_ebitda"))

    available = [value for value in [pe_ratio, forward_pe, price_to_sales, ev_to_ebitda] if value is not None]
    if len(available) < 2:
        return False
    if pe_ratio is not None and pe_ratio > MAX_BUY_PE:
        return False
    if forward_pe is not None and forward_pe > MAX_BUY_FORWARD_PE:
        return False
    if price_to_sales is not None and price_to_sales > MAX_BUY_PRICE_TO_SALES:
        return False
    if ev_to_ebitda is not None and ev_to_ebitda > MAX_BUY_EV_TO_EBITDA:
        return False
    return True


def _metric_line(row):
    metrics = [
        ("PE", row.get("pe_ratio")),
        ("Fwd PE", row.get("forward_pe")),
        ("P/S", row.get("price_to_sales")),
        ("EV/EBITDA", row.get("ev_to_ebitda")),
        ("Margen seguridad", row.get("margin_of_safety_pct")),
        ("Valor justo", row.get("conservative_fair_value")),
        ("Peer score", row.get("peer_relative_score")),
        ("ROE", row.get("roe")),
        ("Margen", row.get("profit_margin")),
    ]
    parts = []
    for label, value in metrics:
        if value is None:
            continue
        number = float(value)
        if label in {"ROE", "Margen", "Margen seguridad"}:
            parts.append(f"{label} {round(number * 100, 1)}%")
        else:
            parts.append(f"{label} {round(number, 2)}")
    return " | ".join(parts) if parts else "Ratios principales no disponibles."


def _ratio_status(value, limit, lower_is_better=True):
    if value is None or limit is None:
        return None
    value = float(value)
    limit = float(limit)
    if limit <= 0:
        return None
    ratio = value / limit
    if lower_is_better:
        if ratio <= 0.85:
            return "comodo"
        if ratio <= 1.05:
            return "cerca del limite razonable"
        return "exigente"
    if ratio >= 1.15:
        return "fuerte"
    if ratio >= 0.95:
        return "razonable"
    return "debil"


def _plain_ratio_explanation(row, mode):
    notes = []
    forward_pe = _float_or_none(row.get("forward_pe"))
    forward_pe_limit = _float_or_none(row.get("adaptive_forward_pe_limit"))
    price_to_sales = _float_or_none(row.get("price_to_sales"))
    price_to_sales_limit = _float_or_none(row.get("adaptive_price_to_sales_limit"))
    ev_to_ebitda = _float_or_none(row.get("ev_to_ebitda"))
    ev_to_ebitda_limit = _float_or_none(row.get("adaptive_ev_to_ebitda_limit"))
    margin_of_safety = _float_or_none(row.get("margin_of_safety_pct"))
    peer_label = row.get("peer_valuation_label")
    primary_metric = row.get("primary_metric")

    if margin_of_safety is not None:
        if margin_of_safety > 0:
            notes.append(f"el precio tiene un margen estimado de {round(margin_of_safety * 100, 1)}% bajo el valor conservador")
        else:
            notes.append(f"el precio esta {round(abs(margin_of_safety) * 100, 1)}% sobre el valor conservador")

    pe_status = _ratio_status(forward_pe, forward_pe_limit)
    if pe_status:
        notes.append(f"ganancias futuras: Forward PE {round(forward_pe, 2)} esta {pe_status} frente al limite {round(forward_pe_limit, 2)}")

    ps_status = _ratio_status(price_to_sales, price_to_sales_limit)
    if ps_status:
        notes.append(f"ventas: P/S {round(price_to_sales, 2)} esta {ps_status} frente al limite {round(price_to_sales_limit, 2)}")

    ev_status = _ratio_status(ev_to_ebitda, ev_to_ebitda_limit)
    if ev_status:
        notes.append(f"flujo operativo: EV/EBITDA {round(ev_to_ebitda, 2)} esta {ev_status} frente al limite {round(ev_to_ebitda_limit, 2)}")

    if peer_label:
        notes.append(f"comparada con empresas similares aparece como {peer_label}")
    if primary_metric:
        notes.append(f"el ratio mas relevante para este caso es {primary_metric}")

    if not notes:
        return "No hay suficientes ratios consistentes para explicar la valoracion con confianza."

    prefix = "Lectura simple"
    if mode == "buy":
        prefix = "Por que podria ser interesante"
    elif mode == "observe":
        prefix = "Por que solo observar"
    elif mode == "sell":
        prefix = "Por que revisar venta"
    return prefix + ": " + "; ".join(notes[:5]) + "."


def build_alert_text(summary, opportunity_rows=None, sell_rows=None, observe_rows=None):
    if opportunity_rows is not None or sell_rows is not None or observe_rows is not None:
        lines = [f"*{summary['alert_title']}*", ""]
        if opportunity_rows:
            lines.append("Oportunidades claras de compra detectadas:")
            for row in opportunity_rows:
                confidence = _normalized_confidence(row.get("confidence_score"))
                lines.append(
                    "- {ticker}: score={score}, confianza={confidence}. {summary}".format(
                        ticker=row.get("ticker"),
                        score=round(float(row.get("final_score") or 0), 2),
                        confidence=round(confidence, 2),
                        summary=f"{_plain_ratio_explanation(row, 'buy')} {row.get('ai_summary') or row.get('ai_opportunity') or 'Ver detalle en Looker Studio.'}",
                    )
                )
        if observe_rows:
            if opportunity_rows:
                lines.append("")
            lines.append("Compras a observar:")
            for row in observe_rows:
                confidence = _normalized_confidence(row.get("confidence_score"))
                lines.append(
                    "- {ticker}: score={score}, confianza={confidence}. {summary}".format(
                        ticker=row.get("ticker"),
                        score=round(float(row.get("final_score") or 0), 2),
                        confidence=round(confidence, 2),
                        summary=f"{_plain_ratio_explanation(row, 'observe')} {row.get('ai_decision_support') or row.get('ai_opportunity') or row.get('ai_summary') or 'Ver detalle en Looker Studio.'}",
                    )
                )
        if sell_rows:
            if opportunity_rows or observe_rows:
                lines.append("")
            lines.append("Alertas claras de venta/sobrevaloracion:")
            for row in sell_rows:
                confidence = _normalized_confidence(row.get("confidence_score"))
                lines.append(
                    "- {ticker}: score_venta={score}, precio_actual={price}, zona_revision={sell_price}, confianza={confidence}. {summary}".format(
                        ticker=row.get("ticker"),
                        score=round(float(row.get("sell_score") or 0), 2),
                        price=round(float(row.get("last_close") or 0), 2),
                        sell_price=round(float(row.get("suggested_sell_price") or 0), 2),
                        confidence=round(confidence, 2),
                        summary=f"{_plain_ratio_explanation(row, 'sell')} {row.get('ai_sell_thesis') or row.get('ai_sell_reasons') or 'Ver detalle en Looker Studio.'}",
                    )
                )
        lines.append("")
        lines.append("Detalle completo en Looker Studio / BigQuery.")
        return "\n".join(lines)

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


def _short_text(text, limit):
    if not text:
        return "Ver detalle en Looker Studio."
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _buy_fields(opportunity_rows):
    fields = []
    for row in opportunity_rows[:DISCORD_MAX_FIELDS_PER_SECTION]:
        ticker = row.get("ticker")
        score = round(float(row.get("final_score") or 0), 2)
        confidence = round(_normalized_confidence(row.get("confidence_score")), 2)
        text = row.get("ai_summary") or row.get("ai_opportunity") or "Ver detalle en Looker Studio."
        fields.append(
            {
                "name": f"{ticker} | score {score} | confianza {confidence}",
                "value": _short_text(text, DISCORD_FIELD_LIMIT),
                "inline": False,
            }
        )
    return fields


def _sell_fields(sell_rows):
    fields = []
    for row in sell_rows[:DISCORD_MAX_FIELDS_PER_SECTION]:
        ticker = row.get("ticker")
        score = round(float(row.get("sell_score") or 0), 2)
        confidence = round(_normalized_confidence(row.get("confidence_score")), 2)
        price = round(float(row.get("last_close") or 0), 2)
        sell_price = round(float(row.get("suggested_sell_price") or 0), 2)
        text = row.get("ai_sell_thesis") or row.get("ai_sell_reasons") or "Ver detalle en Looker Studio."
        fields.append(
            {
                "name": f"{ticker} | venta {score} | actual {price} | revisar {sell_price} | confianza {confidence}",
                "value": _short_text(text, DISCORD_FIELD_LIMIT),
                "inline": False,
            }
        )
    return fields


def _discord_buy_embed(row):
    ticker = row.get("ticker")
    score = round(float(row.get("final_score") or 0), 2)
    confidence = round(_normalized_confidence(row.get("confidence_score")), 2)
    return {
        "title": f"{ticker} | oportunidad clara de compra",
        "description": _short_text(row.get("ai_summary") or row.get("ai_opportunity"), DISCORD_FIELD_LIMIT),
        "color": DISCORD_GREEN,
        "fields": [
            {"name": "Lectura rapida", "value": _short_text(_plain_ratio_explanation(row, "buy"), DISCORD_FIELD_LIMIT), "inline": False},
            {"name": "Score", "value": str(score), "inline": True},
            {"name": "Confianza", "value": str(confidence), "inline": True},
            {"name": "Ratios usados", "value": _metric_line(row), "inline": False},
            {
                "name": "Interpretacion",
                "value": _short_text(row.get("ai_fair_value_view") or row.get("signal_reason"), DISCORD_FIELD_LIMIT),
                "inline": False,
            },
            {
                "name": "Soporte",
                "value": _short_text(row.get("ai_decision_support"), DISCORD_FIELD_LIMIT),
                "inline": False,
            },
            {
                "name": "Riesgos",
                "value": _short_text(row.get("ai_risks"), DISCORD_FIELD_LIMIT),
                "inline": False,
            },
        ],
        "footer": {"text": "Detalle completo en Looker Studio / BigQuery"},
    }


def _discord_observe_buy_embed(row):
    ticker = row.get("ticker")
    score = round(float(row.get("final_score") or 0), 2)
    confidence = round(_normalized_confidence(row.get("confidence_score")), 2)
    return {
        "title": f"{ticker} | compra a observar",
        "description": _short_text(row.get("ai_opportunity") or row.get("ai_summary"), DISCORD_FIELD_LIMIT),
        "color": DISCORD_GOLD,
        "fields": [
            {"name": "Lectura rapida", "value": _short_text(_plain_ratio_explanation(row, "observe"), DISCORD_FIELD_LIMIT), "inline": False},
            {"name": "Score", "value": str(score), "inline": True},
            {"name": "Confianza", "value": str(confidence), "inline": True},
            {"name": "Estado IA", "value": str(row.get("ai_final_alert_action") or "NO_DEFINIDO"), "inline": True},
            {"name": "Ratios usados", "value": _metric_line(row), "inline": False},
            {
                "name": "Por que observar",
                "value": _short_text(row.get("ai_decision_support") or row.get("ai_fair_value_view"), DISCORD_FIELD_LIMIT),
                "inline": False,
            },
            {
                "name": "Riesgos / cautela",
                "value": _short_text(row.get("ai_risks") or row.get("data_discrepancies"), DISCORD_FIELD_LIMIT),
                "inline": False,
            },
        ],
        "footer": {"text": "Compra a observar: no es compra clara. Validar precio, datos y tesis antes de actuar."},
    }


def _discord_sell_embed(row):
    ticker = row.get("ticker")
    score = round(float(row.get("sell_score") or 0), 2)
    confidence = round(_normalized_confidence(row.get("confidence_score")), 2)
    price = round(float(row.get("last_close") or 0), 2)
    sell_price = round(float(row.get("suggested_sell_price") or 0), 2)
    return {
        "title": f"{ticker} | alerta clara de venta",
        "description": _short_text(row.get("ai_sell_thesis") or row.get("ai_sell_reasons"), DISCORD_FIELD_LIMIT),
        "color": DISCORD_RED,
        "fields": [
            {"name": "Lectura rapida", "value": _short_text(_plain_ratio_explanation(row, "sell"), DISCORD_FIELD_LIMIT), "inline": False},
            {"name": "Score venta", "value": str(score), "inline": True},
            {"name": "Precio actual", "value": str(price), "inline": True},
            {"name": "Zona revision", "value": str(sell_price), "inline": True},
            {"name": "Confianza", "value": str(confidence), "inline": True},
            {"name": "Ratios usados", "value": _metric_line(row), "inline": False},
            {
                "name": "Interpretacion",
                "value": _short_text(row.get("ai_sell_decision_support") or row.get("ai_sell_price_view"), DISCORD_FIELD_LIMIT),
                "inline": False,
            },
        ],
        "footer": {"text": "No es recomendacion personalizada. Revisar detalle en Looker Studio / BigQuery"},
    }


def build_discord_payload(summary, opportunity_rows, sell_rows=None, observe_rows=None):
    sell_rows = sell_rows or []
    observe_rows = observe_rows or []
    embeds = []
    if opportunity_rows:
        embeds.append(
            {
                "title": "Oportunidades claras de compra",
                "description": "Acciones con senal `COMPRAR_OBSERVAR`, score alto y confianza suficiente.",
                "color": DISCORD_GREEN,
                "fields": _buy_fields(opportunity_rows),
                "footer": {"text": "Detalle completo en Looker Studio / BigQuery"},
            }
        )
    if observe_rows:
        embeds.append(
            {
                "title": "Compras a observar",
                "description": "Acciones con `COMPRAR_OBSERVAR` que no califican como compra clara por confianza, datos o valuation guardrails.",
                "color": DISCORD_GOLD,
                "fields": _buy_fields(observe_rows),
                "footer": {"text": "No es alerta de compra clara. Revisar detalle completo en dashboard / BigQuery"},
            }
        )
    if sell_rows:
        embeds.append(
            {
                "title": "Alertas claras de venta",
                "description": "Acciones con `VENTA_CLARA` o `VENDER_OBSERVAR`, multiples exigentes y confianza suficiente.",
                "color": DISCORD_RED,
                "fields": _sell_fields(sell_rows),
                "footer": {"text": "No es recomendacion personalizada. Revisar detalle en Looker Studio / BigQuery"},
            }
        )
    if not embeds:
        embeds.append(
            {
                "title": summary.get("alert_title") or "Cartera sin alertas claras",
                "description": "No se detectaron compras ni ventas claras con los umbrales actuales.",
                "color": DISCORD_GOLD,
            }
        )
    return {"embeds": embeds}


def build_discord_messages(summary, opportunity_rows, sell_rows=None, observe_rows=None):
    messages = []
    for row in (opportunity_rows or [])[:DISCORD_MAX_FIELDS_PER_SECTION]:
        messages.append({"embeds": [_discord_buy_embed(row)]})
    for row in (observe_rows or [])[:DISCORD_MAX_FIELDS_PER_SECTION]:
        messages.append({"embeds": [_discord_observe_buy_embed(row)]})
    for row in (sell_rows or [])[:DISCORD_MAX_FIELDS_PER_SECTION]:
        messages.append({"embeds": [_discord_sell_embed(row)]})
    if not messages:
        messages.append(build_discord_payload(summary, [], []))
    return messages


def send_webhook_alert(config, summary, analysis_rows=None):
    url = config.get("alert_webhook_url")
    if not url:
        return False, "ALERT_WEBHOOK_URL not configured"

    opportunity_rows = clear_opportunity_rows(analysis_rows or [])
    observe_rows = observe_opportunity_rows(analysis_rows or [], opportunity_rows)
    sell_rows = clear_sell_rows(analysis_rows or [])
    if not opportunity_rows and not observe_rows and not sell_rows:
        return False, "NO_CLEAR_OPPORTUNITIES"

    text = build_alert_text(summary, opportunity_rows, sell_rows, observe_rows)
    webhook_type = _detect_webhook_type(config)
    if webhook_type == "discord":
        errors = []
        for payload in build_discord_messages(summary, opportunity_rows, sell_rows, observe_rows):
            response = requests.post(url, json=payload, timeout=30)
            if response.status_code >= 300:
                errors.append(f"{response.status_code}: {response.text}")
        if errors:
            return False, "Webhook error: " + " | ".join(errors)
        return True, None
    else:
        payload = {"text": _truncate_text(text, SLACK_TEXT_LIMIT)}

    response = requests.post(url, json=payload, timeout=30)
    if response.status_code >= 300:
        return False, f"Webhook error {response.status_code}: {response.text}"
    return True, None


def build_weekly_discord_payload(summary):
    concise_summary = summary.get("discord_summary") or summary.get("weekly_summary")
    return {
        "embeds": [
            {
                "title": summary.get("alert_title") or "Resumen semanal de cartera",
                "description": _short_text(concise_summary, 950),
                "color": DISCORD_BLUE,
                "fields": [
                    {"name": "Cambios clave", "value": _short_text(summary.get("state_changes"), 450), "inline": False},
                    {"name": "Riesgos", "value": _short_text(summary.get("risk_changes"), 450), "inline": False},
                    {"name": "Vigilar", "value": _short_text(summary.get("watch_next_week"), 450), "inline": False},
                ],
                "footer": {"text": "Resumen corto. Reporte completo disponible en BigQuery/dashboard."},
            }
        ]
    }


def send_weekly_webhook_alert(config, summary):
    url = config.get("alert_webhook_url")
    if not url:
        return False, "ALERT_WEBHOOK_URL not configured"

    webhook_type = _detect_webhook_type(config)
    if webhook_type == "discord":
        response = requests.post(url, json=build_weekly_discord_payload(summary), timeout=30)
    else:
        response = requests.post(url, json={"text": _truncate_text(summary.get("discord_summary") or summary.get("alert_body") or summary.get("weekly_summary") or "", SLACK_TEXT_LIMIT)}, timeout=30)

    if response.status_code >= 300:
        return False, f"Webhook error {response.status_code}: {response.text}"
    return True, None
