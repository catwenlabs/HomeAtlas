"""Static choices the setup wizard prefills for first-time initialization."""

from dataclasses import dataclass

from app.modules.categories.defaults import DEFAULT_CATEGORIES
from app.modules.currencies.defaults import BUILTIN_CURRENCIES


@dataclass(frozen=True)
class TimezoneOption:
    value: str
    label: str


TIMEZONES: tuple[TimezoneOption, ...] = (
    TimezoneOption("Asia/Shanghai", "中国标准时间 (UTC+8)"),
    TimezoneOption("Asia/Hong_Kong", "香港时间 (UTC+8)"),
    TimezoneOption("Asia/Tokyo", "日本标准时间 (UTC+9)"),
    TimezoneOption("Asia/Singapore", "新加坡时间 (UTC+8)"),
    TimezoneOption("Europe/London", "伦敦时间"),
    TimezoneOption("Europe/Paris", "巴黎时间"),
    TimezoneOption("America/New_York", "纽约时间"),
    TimezoneOption("America/Los_Angeles", "洛杉矶时间"),
    TimezoneOption("Australia/Sydney", "悉尼时间"),
    TimezoneOption("UTC", "协调世界时 (UTC)"),
)


def setup_options() -> dict[str, object]:
    return {
        "currencies": [
            {
                "code": item.code,
                "name": item.name,
                "symbol": item.symbol,
                "decimal_places": item.decimal_places,
            }
            for item in BUILTIN_CURRENCIES
        ],
        "categories": [
            {
                "name": item.name,
                "category_type": item.category_type.value,
                "sort_order": item.sort_order,
                "icon": item.icon,
            }
            for item in DEFAULT_CATEGORIES
        ],
        "timezones": [{"value": item.value, "label": item.label} for item in TIMEZONES],
    }
