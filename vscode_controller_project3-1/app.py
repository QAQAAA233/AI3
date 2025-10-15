"""Application entrypoint for the AI automation controller."""
from __future__ import annotations

from ai_controller import create_app
from ai_controller.webapp import launch_desktop

app = create_app()


if __name__ == "__main__":
    launch_desktop(app)
