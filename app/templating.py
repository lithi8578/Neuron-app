from pathlib import Path
from urllib.parse import quote

from fastapi.templating import Jinja2Templates

from .config import settings
from .scheduling import RATING_LABELS

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def obsidian_url(note) -> str:
    """obsidian://open 連結；有資料夾就用「資料夾/名稱」。"""
    path = f"{note.folder.strip('/')}/{note.name}" if note.folder else note.name
    return f"obsidian://open?vault={quote(settings.obsidian_vault)}&file={quote(path)}"


def short_date(d) -> str:
    return f"{d.month}/{d.day}" if d else "—"


templates.env.globals.update(obsidian_url=obsidian_url, rating_labels=RATING_LABELS)
templates.env.filters["short_date"] = short_date
