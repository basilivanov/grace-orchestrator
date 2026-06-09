from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="Todo Admin Backend")

items: list[dict[str, object]] = []
_next_id = 1


class ItemCreate(BaseModel):
    title: str


class ItemOut(BaseModel):
    id: int
    title: str
    done: bool


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/items", response_model=list[ItemOut])
def list_items() -> list[ItemOut]:
    return [ItemOut(**item) for item in items]


@app.post("/items", response_model=ItemOut, status_code=201)
def create_item(body: ItemCreate) -> ItemOut:
    global _next_id
    item = ItemOut(id=_next_id, title=body.title, done=False)
    _next_id += 1
    items.append(item.model_dump())
    return item


@app.get("/items/report", response_class=HTMLResponse)
def items_report() -> str:
    rows = "".join(
        f"<tr><td>{item['id']}</td><td>{item['title']}</td><td>{item['done']}</td></tr>"
        for item in items
    )
    return (
        "<!DOCTYPE html>"
        "<html><body><table>"
        "<thead><tr><th>ID</th><th>Title</th><th>Done</th></tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table></body></html>"
    )
