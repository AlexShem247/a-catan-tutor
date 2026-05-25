import argparse
import sys
from random import randint

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication


def build_application(argv: list[str] | None = None) -> QApplication:
    app = QApplication(argv or sys.argv)
    app.setApplicationName("Catan Tutor")
    app.setOrganizationName("Prototype")
    app.setFont(QFont("Arial"))
    app.setQuitOnLastWindowClosed(True)
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Catan game.")
    parser.add_argument("--seed", type=int, default=None, help="Optional seed for deterministic games")
    args, _unknown_args = parser.parse_known_args(argv)

    app_argv = sys.argv if argv is None else [sys.argv[0], *argv]
    app = build_application(app_argv)

    from config.player_policies import EVO_VS_RULE_BASED, STANDARD_SINGLEPLAYER
    from controllers.GameController import GameController
    from view.MainWindow import MainWindow
    from view.QtView import QtView

    seed = args.seed if args.seed is not None else randint(0, 2**31 - 1)
    controller = GameController(
        STANDARD_SINGLEPLAYER,
        EVO_VS_RULE_BASED,
        game_seed=seed,
    )

    controller.view = QtView(MainWindow(), controller)
    controller.start_game()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
