from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Todo Backend")

items: list[dict[str, Any]] = []
_next_id = 1


class ItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=99)


class ItemOut(BaseModel):
    id: int
    title: str
    done: bool


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/items", response_model=list[ItemOut])
def list_items() -> list[ItemOut]:
    return [ItemOut.model_validate(item) for item in items]


@app.post("/items", response_model=ItemOut, status_code=201)
def create_item(body: ItemCreate) -> ItemOut:
    global _next_id
    item = ItemOut(id=_next_id, title=body.title, done=False)
    _next_id += 1
    items.append(item.model_dump())
    return item
