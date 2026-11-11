"""Pydantic schemas for core currencies."""

from pydantic import BaseModel, ConfigDict


class CurrencyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    symbol: str
    decimal_places: int
    is_active: bool


class CurrencyBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    symbol: str
    decimal_places: int


__all__ = ["CurrencyBrief", "CurrencyRead"]
