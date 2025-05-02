To generate comprehensive tests for the provided FastAPI application using `pytest`, we need to ensure that we cover various aspects such as function/method testing, edge cases, and exception handling. Below is a complete set of `pytest` tests for the provided FastAPI application.

First, ensure you have `pytest` installed:
```sh
pip install pytest
```

Next, create a test file, e.g., `test_main.py`, and add the following tests:

```python
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_read_main():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to the Retro NES-Style Flash Game API"}

def test_highscores_endpoint():
    response = client.get("/highscores")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_add_highscore():
    new_score = {"player": "TestPlayer", "score": 100}
    response = client.post("/highscores", json=new_score)
    assert response.status_code == 201
    assert response.json() == new_score

def test_add_highscore_invalid():
    invalid_score = {"player": "TestPlayer"}
    response = client.post("/highscores", json=invalid_score)
    assert response.status_code == 422

def test_get_highscore_by_player():
    player_name = "TestPlayer"
    response = client.get(f"/highscores/{player_name}")
    assert response.status_code == 200
    assert response.json()["player"] == player_name

def test_get_highscore_by_player_not_found():
    player_name = "NonExistentPlayer"
    response = client.get(f"/highscores/{player_name}")
    assert response.status_code == 404

def test_add_highscore_negative_score():
    new_score = {"player": "NegativePlayer", "score": -10}
    response = client.post("/highscores", json=new_score)
    assert response.status_code == 422

def test_add_highscore_non_integer_score():
    new_score = {"player": "NonIntegerPlayer", "score": "hundred"}
    response = client.post("/highscores", json=new_score)
    assert response.status_code == 422

def test_add_highscore_empty_player():
    new_score = {"player": "", "score": 100}
    response = client.post("/highscores", json=new_score)
    assert response.status_code == 422

def test_add_highscore_long_player_name():
    new_score = {"player": "a" * 101, "score": 100}
    response = client.post("/highscores", json=new_score)
    assert response.status_code == 422

def test_add_highscore_large_score():
    new_score = {"player": "LargeScorePlayer", "score": 1000000000}
    response = client.post("/highscores", json=new_score)
    assert response.status_code == 201
    assert response.json() == new_score
```

### Explanation:

1. **Function/Method Testing**:
   - `test_read_main()`: Tests the root endpoint.
   - `test_highscores_endpoint()`: Tests the `/highscores` endpoint.
   - `test_add_highscore()`: Tests adding a valid high score.
   - `test_get_highscore_by_player()`: Tests retrieving a high score by player name.

2. **Edge Cases**:
   - `test_get_highscore_by_player_not_found()`: Tests retrieving a high score for a non-existent player.
   - `test_add_highscore_negative_score()`: Tests adding a high score with a negative score.
   - `test_add_highscore_non_integer_score()`: Tests adding a high score with a non-integer score.
   - `test_add_highscore_empty_player()`: Tests adding a high score with an empty player name.
   - `test_add_highscore_long_player_name()`: Tests adding a high score with a very long player name.
   - `test_add_highscore_large_score()`: Tests adding a high score with a very large score.

3. **Exception Handling**:
   - `test_add_highscore_invalid()`: Tests adding an invalid high score (missing score).

### Running the Tests:

To run the tests, use the following command in your terminal:
```sh
pytest test_main.py
```

This will execute all the tests and provide a summary of the results.