"""Shared geographic conversions."""


def dms_to_decimal(deg, minute, sec, direction):
    """DMS components -> signed WGS84 decimal degrees; None if unusable.

    Tolerates strings, blanks and NaN (pandas). direction: N/S/E/W.
    """
    def num(x, default=None):
        if x is None or (isinstance(x, float) and x != x) or x == "":
            return default
        try:
            v = float(x)
        except (TypeError, ValueError):
            return None
        return None if v != v else v          # NaN guard (pandas blanks)
    d = num(deg)
    m = num(minute, 0.0)
    s = num(sec, 0.0)
    if d is None or m is None or s is None:
        return None
    if direction not in ("N", "S", "E", "W"):
        return None
    if not (0 <= m < 60 and 0 <= s < 60):
        return None
    value = d + m / 60 + s / 3600
    if direction in ("S", "W"):
        value = -value
    if abs(value) > 180 or (direction in ("N", "S") and abs(value) > 90):
        return None
    return round(value, 6)
