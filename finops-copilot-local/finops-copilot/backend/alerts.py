"""Webhook alerts (Slack / Microsoft Teams / Google Chat)."""
from typing import Dict, Any, List
import httpx


def _fmt(n: float) -> str:
    return f"R$ {n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_summary_text(summary: Dict[str, Any], recs: Dict[str, Any], threshold: float) -> Dict[str, Any]:
    top = sorted(recs["by_category"], key=lambda c: -c["total_savings"])[:5]
    lines = [
        f"*Gasto do período:* {_fmt(summary['current_month'])} ({summary['variation_pct']:+.1f}% vs anterior)",
        f"*Economia potencial:* {_fmt(recs['total_savings'])}/mês em {recs['total_count']} recomendações",
        f"*Limite configurado:* {_fmt(threshold)}",
        "",
        "*Top categorias:*",
    ] + [f"• {c['category_label']}: {_fmt(c['total_savings'])} ({c['count']})" for c in top]
    return {"title": "Azure FinOps Copilot — Resumo semanal", "lines": lines}


def build_payload(provider: str, title: str, lines: List[str]) -> Dict[str, Any]:
    text = "\n".join(lines)
    if provider == "teams":
        body = [{"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Large"}]
        body += [{"type": "TextBlock", "text": l.replace("*", "**"), "wrap": True} for l in lines if l]
        return {"type": "message", "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard", "version": "1.4", "body": body},
        }]}
    if provider == "slack":
        return {"text": f"*{title}*\n{text}"}
    return {"text": f"*{title}*\n{text}"}  # google_chat


async def send_webhook(provider: str, url: str, title: str, lines: List[str]) -> None:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, json=build_payload(provider, title, lines))
        r.raise_for_status()
