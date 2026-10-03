from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Login(Model):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=512)


class Stamp(Model):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float = Field(gt=0, le=100000)


class Complete(Model):
    signature_status: Literal['CON_FIRMA', 'SENZA_FIRMA'] | None = None
    note: str = Field(default='', max_length=1000)


class Item(Model):
    code: str = Field(max_length=100)
    lot: str = Field(default='', max_length=150)
    quantity: float = Field(gt=0, le=100000)
    description: str = Field(default='', max_length=1000)
    expiry: date | None = None
    lotless: bool = False
    structure_stock: bool = False
    manufacturer: str = Field(default='', max_length=200)
    verified: bool = False
    manual_price: float | None = Field(default=None, ge=0, le=1000000)


class Scarico(Model):
    request_id: str = Field(pattern=r'^[a-zA-Z0-9-]{16,80}$')
    customer_code: str = Field(min_length=1, max_length=100)
    warehouse: str = Field(min_length=1, max_length=100)
    line: Literal['TRAUMA', 'PROTESICA']
    procedure_date: date
    clinical_record: str = Field(default='', max_length=200)
    surgeon: str = Field(default='', max_length=200)
    items: list[Item] = Field(min_length=1, max_length=300)


class ExportItems(Model):
    items: list[Item] = Field(min_length=1, max_length=300)
