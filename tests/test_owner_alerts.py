"""Алерт владельцу о кончившемся балансе Anthropic должен называть организацию.

Прецедент 28.10.2026: по ссылке из алерта открылась рабочая организация
с положительным балансом, а кончились деньги в личной, где ключ бота.
"""

from unittest.mock import patch

from core.infra import owner_alerts


def test_low_balance_alert_names_key_org_and_billing_link():
    with patch.object(owner_alerts, "notify_owner") as notify:
        owner_alerts.notify_owner_low_anthropic_balance()

    alert_key, text = notify.call_args.args
    assert alert_key == "anthropic_low_balance"
    assert "healthvault-bot" in text
    assert "Individual Org" in text
    assert "platform.claude.com/settings/billing" in text
