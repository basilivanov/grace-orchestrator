from fastapi.testclient import TestClient

try:
    from backend_fastapi_todo.main import app, items
except ModuleNotFoundError:
    from main import app, items

client = TestClient(app)


def setup_function() -> None:
    items.clear()
    app.dependency_overrides.clear()
    try:
        import backend_fastapi_todo.main as main_module
    except ModuleNotFoundError:
        import main as main_module

    main_module._next_id = 1


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_item() -> None:
    response = client.post("/items", json={"title": "Buy milk"})

    assert response.status_code == 201
    assert response.json() == {"id": 1, "title": "Buy milk", "done": False}


def test_list_items() -> None:
    client.post("/items", json={"title": "Buy milk"})
    client.post("/items", json={"title": "Walk dog"})

    response = client.get("/items")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 1, "title": "Buy milk", "done": False},
        {"id": 2, "title": "Walk dog", "done": False},
    ]


def test_create_item_empty_title() -> None:
    response = client.post("/items", json={"title": ""})
    assert response.status_code == 422


def test_create_item_too_long_title() -> None:
    response = client.post("/items", json={"title": "a" * 100})
    assert response.status_code == 422
