import pytest

from serialtek.timestamp import HALF_NANOSECOND, PICOSECOND, Ticks, Timestamp


@pytest.mark.parametrize(
    "dotted, ticks_int, base",
    # fmt: off
    [
        ("001.001.001.001.5", 2_002_002_003, HALF_NANOSECOND),
        ("069.515.382.208.5", 139030764417 , HALF_NANOSECOND),
        ("069.515.383.110.0", 139030766220 , HALF_NANOSECOND),
        ("000.000.000.000.0", 0            , HALF_NANOSECOND),
        ("999.999.999.999.5", 1999999999999, HALF_NANOSECOND),
        ("001.002.003.004.5", 2004006009   , HALF_NANOSECOND),
        ("123.456.789.123.456", 123_456_789_123_456, PICOSECOND),
    ],
    # fmt: on
)
def test_ticks_round_trip(ticks_int: int, dotted: str, base: int) -> None:
    ticks = Ticks(dotted, base)
    assert str(ticks) == dotted
    assert ticks == ticks_int
    assert Ticks(Timestamp(dotted), base) == ticks
