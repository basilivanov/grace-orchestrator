from src.hello import greet


def test_greet():
    assert greet('World') == 'Hello, World!'
