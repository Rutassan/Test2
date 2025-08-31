import sys

from game import Game
from renderer_gui import GuiApp


def main():
    game = Game()
    app = GuiApp(game)
    app.root.mainloop()


if __name__ == "__main__":
    main()

