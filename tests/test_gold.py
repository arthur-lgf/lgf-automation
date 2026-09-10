"""Monthly Gold Report CLI helpers (scripts/gold.py)."""
import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gold.py"


def _gold():
    spec = importlib.util.spec_from_file_location("gold_cli", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gold_defaults_are_monthly_v_y_block():
    gold = _gold()
    assert gold.GOLD_RANGE == "V1:Y50"
    assert gold.GOLD_TITLE == "Monthly Gold Report"
    assert gold.GOLD_GID == 170384010
    assert gold.GOLD_CHANNEL_ID == "C0ATW4FSK0X"
    assert gold.GOLD_CHANNEL_IDS == ("C0ATW4FSK0X",)
    assert gold.GOLD_THEME == "gold"


def test_destination_channels_adds_extra_without_duplicating():
    gold = _gold()
    assert gold.destination_channels("C111", *gold.GOLD_CHANNEL_IDS) == [
        "C111",
        "C0ATW4FSK0X",
    ]
    assert gold.destination_channels("C0ATW4FSK0X", *gold.GOLD_CHANNEL_IDS) == [
        "C0ATW4FSK0X",
    ]
    assert gold.destination_channels("C111", "") == ["C111"]


def test_no_data_text_says_gold_not_sales():
    gold = _gold()
    text = gold._no_data_text([["MONTHLY GOLD REPORT"], ["Rank", "Sep"]], "Monthly Gold Report")
    assert "gold" in text.lower()
    assert "sales" not in text.lower()


class _Settings:
    def __init__(self, gold=None, sales="xoxb-sales"):
        self.gold_slack_bot_token = gold
        self.slack_bot_token = sales


def test_slack_token_prefers_gold_bot():
    gold = _gold()
    assert gold.slack_token(_Settings(gold="xoxb-gold")) == "xoxb-gold"


def test_slack_token_falls_back_to_sales_bot():
    gold = _gold()
    assert gold.slack_token(_Settings(gold=None)) == "xoxb-sales"
