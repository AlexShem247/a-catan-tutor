# Catan Explainable AI Tutor

**Catan Explainable AI Tutor** is a Python implementation of **Catan** focused on AI experimentation, explainability, teaching, and play. The project includes human and AI players, trade negotiation, building placement, tutor feedback, and full game flow management through a PyQt desktop interface.

## Installing Requirements

Before running the game or tests, install the required Python packages. You can do this using `pip`:

```bash
pip install -r requirements.txt
```

Make sure you are using Python 3.12 or higher for compatibility.

## Running the Game

The game runs through the PyQt GUI:

```bash
python play_game.py
```

## Game Modes

The application supports four game modes:

- `Play`: standard interactive play with the explainable tutor running in the background for feedback collection.
- `Tutor`: interactive play with tutor guidance and feedback shown directly during decisions.
- `Simulation`: automated AI-vs-AI play for observation and testing.
- `Guided`: AI-driven play with move explanations shown, useful for inspecting the policy's reasoning.

## Running Tests

All unit tests are located in the `tests/` directory. You can run them using Python's built-in `unittest` module:

```bash
python -m unittest discover -s tests
```
