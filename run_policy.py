"""Pure accounting and recognition-size rules; safe to test without a GUI."""

import math

DROP_RATES = {"covenant": 0.006602509, "mystic": 0.001700646,
              "friendship": 0.191772874}
SLOTS_PER_SHOP = 6
SKYSTONES_PER_REFRESH = 3


def format_duration(seconds, decimals=0):
    """Present seconds as seconds, minutes/seconds, or hours/minutes/seconds.

    Duration values remain in seconds internally for performance calculations
    and data exports. Round once before splitting to avoid displaying 60s.
    """
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Duration must be a finite nonnegative number")
    if decimals < 0 or decimals > 3:
        raise ValueError("Duration precision must be between 0 and 3")
    rounded = round(seconds, decimals)
    hours = int(rounded // 3600)
    minutes = int((rounded % 3600) // 60)
    remaining = rounded - hours * 3600 - minutes * 60
    seconds_width = 2 + (decimals + 1 if decimals else 0)
    if hours:
        return f"{hours}h {minutes:02d}m {remaining:0{seconds_width}.{decimals}f}s"
    if minutes:
        return f"{minutes}m {remaining:0{seconds_width}.{decimals}f}s"
    return f"{remaining:.{decimals}f}s"


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
    """Expected purchased offers, assuming at most one of each item per shop.

    Interpret the published drop rate as a per-slot chance across six slots,
    then count a shop only once if that currency appears in multiple rolls.
    This model is provisional until the game's slot generation is verified.
    """
    if shops_reviewed < 0:
        raise ValueError("Shop count must be nonnegative")
    return {item: shops_reviewed * (1 - (1 - rate) ** SLOTS_PER_SHOP)
            for item, rate in DROP_RATES.items()}


def recognition_scale(content_width):
    if content_width <= 0:
        raise ValueError("Game content width must be positive")
    return round(1.5 * content_width / 1280, 4)
