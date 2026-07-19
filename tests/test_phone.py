from core.phone import normalize_phone


def test_italy_adds_country_code():
    assert normalize_phone("3331234567") == "393331234567"
    assert normalize_phone("340123456") == "39340123456"

def test_removes_plus_and_zeros():
    assert normalize_phone("+393331234567") == "393331234567"
    assert normalize_phone("00393331234567") == "393331234567"

def test_handles_spaces():
    assert normalize_phone("+39 333 123 4567") == "393331234567"

def test_empty_string():
    assert normalize_phone("") == ""
