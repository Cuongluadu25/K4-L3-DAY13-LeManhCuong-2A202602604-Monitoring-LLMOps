from app.pii import scrub_text


def test_scrub_email() -> None:
    out = scrub_text("Email me at student@vinuni.edu.vn")
    assert "student@" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_common_vietnamese_phone_formats() -> None:
    phone_numbers = (
        "0901234567",
        "090 123 4567",
        "090.123.4567",
        "090-123-4567",
        "+84 90 123 4567",
    )

    for phone_number in phone_numbers:
        out = scrub_text(f"Contact: {phone_number}")
        assert phone_number not in out
        assert "REDACTED_PHONE_VN" in out


def test_scrub_cccd() -> None:
    cccd = "012345678901"
    out = scrub_text(f"CCCD: {cccd}")
    assert cccd not in out
    assert "REDACTED_CCCD" in out


def test_scrub_credit_card_formats() -> None:
    cards = (
        "4111111111111111",
        "4111 1111 1111 1111",
        "4111-1111-1111-1111",
    )

    for card in cards:
        out = scrub_text(f"Card: {card}")
        assert card not in out
        assert "REDACTED_CREDIT_CARD" in out


def test_scrub_vietnamese_passport() -> None:
    out = scrub_text("Passport B1234567 issued in Ha Noi")
    assert "B1234567" not in out
    assert "REDACTED_PASSPORT_VN" in out


def test_scrub_multiple_pii_types_in_one_text() -> None:
    text = (
        "Email student@vinuni.edu.vn, phone 090 123 4567, "
        "CCCD 012345678901, card 4111 1111 1111 1111"
    )
    out = scrub_text(text)

    assert "student@vinuni.edu.vn" not in out
    assert "090 123 4567" not in out
    assert "012345678901" not in out
    assert "4111 1111 1111 1111" not in out
    for marker in (
        "REDACTED_EMAIL",
        "REDACTED_PHONE_VN",
        "REDACTED_CCCD",
        "REDACTED_CREDIT_CARD",
    ):
        assert marker in out
