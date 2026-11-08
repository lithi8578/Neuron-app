"""所有設定都從環境變數讀取。本機用 .env，Cloud Run 用 Secret Manager。"""

import os
import secrets


def _bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip() or "sqlite:///./local.db"
    # Neon 給的是 postgresql://...，SQLAlchemy 要指定用 psycopg 驅動
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Settings:
    def __init__(self) -> None:
        # Cloud Run 一定會設定 K_SERVICE，用來判斷是否在正式環境
        self.on_cloud_run = "K_SERVICE" in os.environ
        self.database_url = _database_url()

        # 開發模式登入：只在本機有效，Cloud Run 上強制關閉
        self.dev_login = _bool(os.environ.get("DEV_LOGIN", "0")) and not self.on_cloud_run

        secret = os.environ.get("SESSION_SECRET", "").strip()
        if not secret:
            if self.on_cloud_run:
                raise RuntimeError("Cloud Run 上必須設定 SESSION_SECRET")
            secret = secrets.token_hex(32)  # 本機：每次重啟會登出，不影響使用
        self.session_secret = secret

        self.google_client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
        self.google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
        self.allowed_emails = {
            e.strip().lower()
            for e in os.environ.get("ALLOWED_EMAILS", "").split(",")
            if e.strip()
        }
        self.obsidian_vault = os.environ.get("OBSIDIAN_VAULT", "Obsidian-Master").strip()

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


settings = Settings()
