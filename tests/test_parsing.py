import re

from trc.pipeline import DT_REGEX, INC_REGEX, parse_filename


def test_incident_regex_examples():
    cases = [
        ("INC0001234567-16062025-2023.vtt", "INC0001234567"),
        ("notes-INC123456789012-01012024-0000.vtt", "INC123456789012"),
        ("INC1234567890_extra-01012024-0000.vtt", "INC1234567890"),
    ]
    for name, expected_inc in cases:
        inc, dt = parse_filename(name)
        assert inc == expected_inc


def test_datetime_regex_examples():
    cases = [
        ("INC0001-16062025-2023.vtt", "16062025-2023"),
        ("prefix-01012024-0000-suffix.vtt", "01012024-0000"),
        ("INC00027452650-05062025-0606.vtt", "05062025-0606"),
    ]
    for name, expected_dt in cases:
        inc, dt = parse_filename(name)
        assert dt == expected_dt


def test_regex_patterns_compiled():
    assert isinstance(INC_REGEX, re.Pattern)
    assert isinstance(DT_REGEX, re.Pattern)
