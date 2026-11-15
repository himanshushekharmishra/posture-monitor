import pytest

pytestmark = pytest.mark.skip(reason="Phase 3")


def test_short_slouch_does_not_alert():
    ...


def test_sustained_slouch_alerts_once_then_cooldown():
    ...


def test_no_person_goes_away():
    ...
