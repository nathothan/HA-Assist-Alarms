"""Tests for datetime_parser.py — no Home Assistant dependency required.

Run with:  python -m pytest tests/test_datetime_parser.py -v
           (or just: pytest)
"""

import importlib.util
import os
import sys
from datetime import datetime, timedelta, timezone

# Import datetime_parser directly from its file so pytest does not trigger
# custom_components/ha_alarms/__init__.py (which requires voluptuous / HA).
_MODULE_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "custom_components",
    "ha_alarms",
    "datetime_parser.py",
)
_spec = importlib.util.spec_from_file_location("datetime_parser", _MODULE_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

ParseAmbiguousError = _mod.ParseAmbiguousError
ParseError = _mod.ParseError
_normalise_time_str = _mod._normalise_time_str
parse_datetime = _mod.parse_datetime

# ---------------------------------------------------------------------------
# Fixed reference: Wednesday 2026-03-25 14:00:00 UTC
# Using 14:00 so AM times (e.g. 8:15 AM) are always "already past" → tomorrow,
# and PM times (8:15 PM = 20:15) are still future → today.
# ---------------------------------------------------------------------------
_REF = datetime(2026, 3, 25, 14, 0, 0, tzinfo=timezone.utc)


def dt(h: int, mi: int, days_ahead: int = 0) -> datetime:
    """Build a UTC datetime at h:mi on the reference date + days_ahead."""
    return _REF.replace(hour=h, minute=mi, second=0, microsecond=0) + timedelta(
        days=days_ahead
    )


# ===========================================================================
# _normalise_time_str — unit tests for the normaliser in isolation
# ===========================================================================

class TestNormaliseTimeStr:
    def test_standard_colon_unchanged(self):
        assert _normalise_time_str("7:30 PM") == "7:30 PM"

    def test_standard_no_space_unchanged(self):
        assert _normalise_time_str("7:30pm") == "7:30pm"

    def test_dot_separator(self):
        assert _normalise_time_str("8.15pm") == "8:15pm"

    def test_dot_separator_with_space_ampm(self):
        assert _normalise_time_str("8.15 pm") == "8:15 pm"

    def test_dot_separator_uppercase_ampm(self):
        assert _normalise_time_str("8.15 PM") == "8:15 PM"

    def test_space_separated_digits(self):
        assert _normalise_time_str("8 15 pm") == "8:15 pm"

    def test_space_separated_digits_no_ampm(self):
        assert _normalise_time_str("8 15") == "8:15"

    def test_dotted_pm(self):
        assert _normalise_time_str("8:15 p.m.").lower() == "8:15 pm"

    def test_dotted_am(self):
        assert _normalise_time_str("8:15 a.m.").lower() == "8:15 am"

    def test_dotted_ampm_uppercase(self):
        assert _normalise_time_str("8:15 P.M.").lower() == "8:15 pm"

    def test_dot_sep_and_dotted_ampm(self):
        # "8.15 p.m." → "8:15 pm"
        assert _normalise_time_str("8.15 p.m.").lower() == "8:15 pm"

    def test_space_sep_and_dotted_ampm(self):
        # "8 15 p.m." → "8:15 pm"
        assert _normalise_time_str("8 15 p.m.").lower() == "8:15 pm"

    def test_noon_unchanged(self):
        assert _normalise_time_str("noon") == "noon"

    def test_midnight_unchanged(self):
        assert _normalise_time_str("midnight") == "midnight"

    def test_24h_unchanged(self):
        assert _normalise_time_str("19:30") == "19:30"


# ===========================================================================
# parse_datetime — faster-whisper variant formats (the core regression suite)
# ===========================================================================

class TestFasterWhisperFormats:
    """These formats were produced by faster-whisper and previously failed."""

    def test_dot_separator_pm(self):
        # "8.15pm" → 20:15 today (still future at 14:00)
        result = parse_datetime("8.15pm", now=_REF)
        assert result == dt(20, 15)

    def test_dot_separator_am(self):
        # "8.15am" → 08:15 tomorrow (already past at 14:00)
        result = parse_datetime("8.15am", now=_REF)
        assert result == dt(8, 15, days_ahead=1)

    def test_dot_separator_space_pm(self):
        # "8.15 pm"
        result = parse_datetime("8.15 pm", now=_REF)
        assert result == dt(20, 15)

    def test_space_separated_pm(self):
        # "8 15 pm"
        result = parse_datetime("8 15 pm", now=_REF)
        assert result == dt(20, 15)

    def test_space_separated_am(self):
        # "8 15 am" → tomorrow (past at 14:00)
        result = parse_datetime("8 15 am", now=_REF)
        assert result == dt(8, 15, days_ahead=1)

    def test_dotted_pm_suffix(self):
        # "8:15 p.m."
        result = parse_datetime("8:15 p.m.", now=_REF)
        assert result == dt(20, 15)

    def test_dotted_am_suffix(self):
        # "8:15 a.m." → tomorrow (past at 14:00)
        result = parse_datetime("8:15 a.m.", now=_REF)
        assert result == dt(8, 15, days_ahead=1)

    def test_dot_sep_and_dotted_pm(self):
        # "8.15 p.m."
        result = parse_datetime("8.15 p.m.", now=_REF)
        assert result == dt(20, 15)

    def test_space_sep_and_dotted_pm(self):
        # "8 15 p.m."
        result = parse_datetime("8 15 p.m.", now=_REF)
        assert result == dt(20, 15)

    def test_space_sep_and_dotted_am(self):
        # "8 15 a.m." → tomorrow
        result = parse_datetime("8 15 a.m.", now=_REF)
        assert result == dt(8, 15, days_ahead=1)

    def test_uppercase_dotted_pm(self):
        # "8:15 P.M."
        result = parse_datetime("8:15 P.M.", now=_REF)
        assert result == dt(20, 15)

    def test_two_digit_hour_dot_sep(self):
        # "10.30 pm"
        result = parse_datetime("10.30 pm", now=_REF)
        assert result == dt(22, 30)

    def test_zero_minutes_dot_sep(self):
        # "9.00 pm"
        result = parse_datetime("9.00 pm", now=_REF)
        assert result == dt(21, 0)

    def test_space_sep_zero_minutes(self):
        # "9 00 pm"
        result = parse_datetime("9 00 pm", now=_REF)
        assert result == dt(21, 0)


# ===========================================================================
# parse_datetime — existing standard formats must still work (regression)
# ===========================================================================

class TestStandardFormats:
    def test_colon_am(self):
        # 9:00 AM is before the 14:00 reference → advances to tomorrow
        assert parse_datetime("9:00 AM", now=_REF) == dt(9, 0, days_ahead=1)

    def test_colon_pm(self):
        assert parse_datetime("7:30 PM", now=_REF) == dt(19, 30)

    def test_no_space_am(self):
        assert parse_datetime("7am", now=_REF) == dt(7, 0, days_ahead=1)

    def test_no_space_pm(self):
        assert parse_datetime("7pm", now=_REF) == dt(19, 0)

    def test_24h(self):
        assert parse_datetime("19:30", now=_REF) == dt(19, 30)

    def test_noon(self):
        # noon is before the 14:00 reference → advances to tomorrow
        assert parse_datetime("noon", now=_REF) == dt(12, 0, days_ahead=1)

    def test_midnight(self):
        # midnight is past 14:00 → tomorrow
        assert parse_datetime("midnight", now=_REF) == dt(0, 0, days_ahead=1)

    def test_relative_minutes(self):
        assert parse_datetime("in 30 minutes", now=_REF) == _REF + timedelta(minutes=30)

    def test_relative_hours(self):
        assert parse_datetime("in 2 hours", now=_REF) == _REF + timedelta(hours=2)

    def test_bare_hour_ambiguous(self):
        import pytest
        with pytest.raises(ParseAmbiguousError):
            parse_datetime("7", now=_REF)

    def test_garbage_raises(self):
        import pytest
        with pytest.raises(ParseError):
            parse_datetime("purple monkey", now=_REF)
