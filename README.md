# English Learning System — Neuron

追蹤每篇 Obsidian 單字筆記（MDNOTE）的閱讀進度，用間隔複習排下一次閱讀日。
規格見 Obsidian `Sketch/English/Neuron 間隔複習系統_需求規格.md`。

- 後端：Python + FastAPI，頁面由伺服器產生（不需要另外的前端專案）
- 資料庫：本機用 SQLite（`local.db`），正式環境用 Neon（Postgres）
- 登入：Google 帳號，只允許 `ALLOWED_EMAILS` 裡的信箱
- 部署：Google Cloud Run

---

## 專案結構

```
app/
  main.py         網址與對應的處理函式（主畫面、完成、復原、新增、編輯、刪除）
  scheduling.py   間隔複習規則：間隔表、完成一次閱讀、復原
  models.py       資料表：notes（筆記狀態）、review_log（每次完成的紀錄）
  auth.py         Google 登入、本機開發模式登入
  config.py       從環境變數讀設定
  db.py           資料庫連線
  templating.py   頁面模板的小工具（obsidian:// 連結、日期格式）
  templates/      HTML 頁面
  static/         CSS
tests/            自動測試（pytest）
```

想改間隔規則，只需要改 `app/scheduling.py`。

---

## 本機執行

第一次：

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
cp .env.example .env
```

`.env` 裡 `DEV_LOGIN=1` 時，登入頁會出現「開發模式登入」，不用設定 Google 也能用。

啟動（改程式會自動重新載入）：

```bash
.venv/Scripts/python -m uvicorn app.main:app --reload --env-file .env --port 8010
```

打開 <http://localhost:8010>。

跑測試：

```bash
.venv/Scripts/python -m pytest -q
```

---

## 部署前要準備的東西

### 1. Neon 資料庫

1. 到 <https://neon.tech> 建立專案，Region 選 **AWS Asia Pacific (Singapore)**（離台灣最近）
2. 複製 Connection string（`postgresql://...?sslmode=require`），這就是 `DATABASE_URL`
3. 想在本機先連 Neon 試試：把它填進 `.env` 的 `DATABASE_URL`，重新啟動即可。資料表會在啟動時自動建立。

### 2. Google 登入

1. 到 <https://console.cloud.google.com>，建立（或選擇）一個專案
2. **APIs & Services → OAuth consent screen**：User type 選 External，填 App 名稱與信箱；
   Test users 加入你自己的 Gmail
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Application type：**Web application**
   - Authorized redirect URIs 加入：
     - `http://localhost:8010/auth/callback`（本機）
     - `https://<Cloud Run 網址>/auth/callback`（目前是 `https://neuron-621748777623.asia-east1.run.app/auth/callback`）
4. 把 Client ID、Client secret 填進 `.env` 的 `GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`

### 3. 部署到 Cloud Run

先安裝 [gcloud CLI](https://cloud.google.com/sdk/docs/install)，然後：

```bash
gcloud auth login
gcloud config set project <你的專案 ID>
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
```

把機密值存進 Secret Manager（每個執行一次，依提示貼上值）：

```bash
gcloud secrets create DATABASE_URL --data-file=-
gcloud secrets create SESSION_SECRET --data-file=-
gcloud secrets create GOOGLE_CLIENT_SECRET --data-file=-
```

讓 Cloud Run 的服務帳號讀得到 secrets（`<專案編號>` 在 GCP 首頁可以看到）：

```bash
gcloud projects add-iam-policy-binding <你的專案 ID> --member=serviceAccount:<專案編號>-compute@developer.gserviceaccount.com --role=roles/secretmanager.secretAccessor
```

部署（在專案資料夾執行，會用 Dockerfile 建置）：

```bash
gcloud run deploy neuron --source . --region asia-east1 --allow-unauthenticated --set-env-vars "GOOGLE_CLIENT_ID=<你的 Client ID>,ALLOWED_EMAILS=lithium8578@gmail.com,OBSIDIAN_VAULT=Obsidian-Master" --set-secrets "DATABASE_URL=DATABASE_URL:latest,SESSION_SECRET=SESSION_SECRET:latest,GOOGLE_CLIENT_SECRET=GOOGLE_CLIENT_SECRET:latest"
```

> `--allow-unauthenticated` 是讓瀏覽器打得開網站；誰能用由 Google 登入 + `ALLOWED_EMAILS` 把關。

部署完會印出網址，回到 Google OAuth client 把 `https://<網址>/auth/callback` 加進 redirect URIs。

---

## 安全設計

- 沒登入的請求一律導向登入頁；只有 `ALLOWED_EMAILS` 裡、且 Google 驗證過的信箱能登入
- 開發模式登入在 Cloud Run 上強制關閉（偵測 `K_SERVICE` 環境變數）
- Cookie 有簽章、`SameSite=Lax`（擋掉其他網站送來的表單），正式環境只走 HTTPS
- 機密值只放在 `.env`（不進 git）與 Secret Manager

## 之後的方向

- 晨報英文段落改成直接查 Neon（GitHub Secret 加 `DATABASE_URL`）
- 改欄位時導入 Alembic 做資料表遷移（目前是啟動時自動建表）
- PTT 精準翻譯訓練

---

## 部署紀錄

- 專案：`project-a79673e6-10c4-4fa2-aa0`，區域 `asia-east1`，服務名稱 `neuron`
- 網址：<https://neuron-621748777623.asia-east1.run.app>
- 新專案第一次部署會遇到 `storage.objects.get` 權限錯誤，解法是給預設運算服務帳號 `roles/run.builder`（已做過）
- 之後更新只要在專案資料夾執行（環境變數與 secrets 會沿用）：

```bash
gcloud run deploy neuron --source . --region asia-east1
```

- 更新某個機密值：`gcloud secrets versions add <名稱> --data-file=-`，再重新部署一次
