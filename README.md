# A Catan Tutor

**A Catan Tutor** is a Python-based implementation of the board game **Catan**, designed for AI experimentation, teaching, and play. The project includes both human and AI players, trade negotiation, building placement, and game flow management.

## Installing Requirements

Before running the game or tests, install the required Python packages. You can do this using `pip`:

```bash
pip install -r requirements.txt
````

Make sure you are using Python 3.12 or higher for compatibility.

## Running the Game

The game by default run with the PyQt GUI. To run the CLI version instead, use the `--cli` flag:

```bash
python play_game.py --cli
```

## Running Tests

All unit tests are located in the `tests/` directory. You can run them using Python's built-in `unittest` module:

```bash
python -m unittest discover -s tests
```