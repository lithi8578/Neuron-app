import os
import sys
import tempfile
from pathlib import Path

# 測試用獨立的暫存 SQLite，並開啟開發模式登入。必須在 import app 之前設定。
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp) / 'test.db'}"
os.environ["DEV_LOGIN"] = "1"
os.environ.pop("K_SERVICE", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
