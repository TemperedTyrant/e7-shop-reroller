"""Pure accounting and recognition-size rules; safe to test without a GUI."""

DROP_RATES = {"covenant": 0.006602509, "mystic": 0.001700646,
              "friendship": 0.191772874}
SLOTS_PER_SHOP = 6
SKYSTONES_PER_REFRESH = 3


def can_refresh(paid_refreshes, limit_mode, limit_value):
    """Return whether *one more* paid refresh is permitted."""
    if paid_refreshes < 0 or limit_value < 0:
        raise ValueError("Refresh counts and limits must be nonnegative")
    if limit_mode == "refreshes":
        return paid_refreshes < limit_value
    if limit_mode == "skystones":
        return (paid_refreshes + 1) * SKYSTONES_PER_REFRESH <= limit_value
    raise ValueError(f"Unknown refresh limit mode: {limit_mode}")


def expected_appearances(shops_reviewed):
    if shops_reviewed < 0:
        raise ValueError("Shop count must be nonnegative")
    return {item: shops_reviewed * SLOTS_PER_SHOP * rate
            for item, rate in DROP_RATES.items()}


def recognition_scale(content_width):
    if content_width <= 0:
        raise ValueError("Game content width must be positive")
    return round(1.5 * content_width / 1280, 4)
