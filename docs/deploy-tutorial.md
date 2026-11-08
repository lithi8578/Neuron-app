# 後端部署教學：從本機原始碼到 Cloud Run 上線

以 Neuron（FastAPI + Neon + Google 登入）的實際部署為例，一步一步說明「我電腦上的一包程式碼」是怎麼變成「任何地方都能打開的網站」。每一步都講**做什麼**、**為什麼**、**背後發生什麼**。

> 本文中的專案資訊（之後查詢用）
> - GCP 專案 ID：`project-a79673e6-10c4-4fa2-aa0`，專案編號：`621748777623`
> - 區域：`asia-east1`（台灣彰化），服務名稱：`neuron`
> - 網址：<https://neuron-621748777623.asia-east1.run.app>

---

## 目錄

0. [全貌：一張圖看懂](#0-全貌一張圖看懂)
1. [本機開發：讓程式「可以被部署」](#1-本機開發讓程式可以被部署)
2. [容器化：Dockerfile](#2-容器化dockerfile)
3. [GCP 基本概念](#3-gcp-基本概念)
4. [準備 gcloud](#4-準備-gcloud)
5. [啟用 API](#5-啟用-api)
6. [機密值：Secret Manager](#6-機密值secret-manager)
7. [部署：`gcloud run deploy` 背後發生什麼](#7-部署gcloud-run-deploy-背後發生什麼)
8. [我們遇到的權限錯誤（IAM 實戰）](#8-我們遇到的權限錯誤iam-實戰)
9. [上線後的 Google 登入設定](#9-上線後的-google-登入設定)
10. [驗證上線結果](#10-驗證上線結果)
11. [日常維運：更新、看 log、回滾](#11-日常維運更新看-log回滾)
12. [費用與效能](#12-費用與效能)
13. [疑難排解](#13-疑難排解)
14. [名詞表](#14-名詞表)

---

## 0. 全貌：一張圖看懂

```
【你的電腦】
  原始碼 + Dockerfile
      │  gcloud run deploy --source .
      ▼
【Cloud Storage】  原始碼打包成 zip 上傳到 bucket
      ▼
【Cloud Build】    照 Dockerfile 建出容器映像檔（image）
      ▼
【Artifact Registry】 存放 image（像是 image 的雲端硬碟）
      ▼
【Cloud Run】      用 image 開出一個「revision」，分配流量，給你 https 網址
      │  執行時讀取
      ├──▶【Secret Manager】 DATABASE_URL、SESSION_SECRET、GOOGLE_CLIENT_SECRET
      └──▶【Neon】 Postgres 資料庫（在 AWS 新加坡）

使用者瀏覽器 ──https──▶ Google 前端（處理 TLS）──http──▶ 你的容器
```

一句話版本：**原始碼 → 打包成容器 → 存起來 → 跑起來 → 給網址**。`gcloud run deploy --source` 一個指令把中間全部串起來，但每一段都是獨立的 GCP 服務，出錯時要知道是哪一段。

---

## 1. 本機開發：讓程式「可以被部署」

能不能順利部署，大半在寫程式時就決定了。關鍵原則只有一個：

### 設定與程式碼分離（12-Factor App 的第三條）

同一份程式碼要在「本機」和「雲端」兩種環境跑，差別只在**設定**：資料庫在哪、密鑰是什麼、是否開放開發模式。這些一律從**環境變數**讀，不寫死在程式裡。

看 `app/config.py`：

```python
url = os.environ.get("DATABASE_URL", "").strip() or "sqlite:///./local.db"
```

- 本機：沒設 `DATABASE_URL` → 用 SQLite 檔案
- 雲端：Cloud Run 從 Secret Manager 注入 `DATABASE_URL` → 用 Neon

程式完全不用改。

### 環境變數從哪裡來

| 環境 | 來源 |
|---|---|
| 本機 | `.env` 檔，啟動時用 `uvicorn ... --env-file .env` 讀入 |
| Cloud Run 一般值 | `--set-env-vars`（例如 `ALLOWED_EMAILS`） |
| Cloud Run 機密值 | `--set-secrets`，從 Secret Manager 讀（第 6 節） |

`.env` 列在 `.gitignore`，**永遠不進 git**。`.env.example` 則進 git，當作「需要哪些變數」的說明書。

### 判斷自己在不在雲端

Cloud Run 一定會設定 `K_SERVICE` 這個環境變數（值是服務名稱）。我們用它把危險功能鎖死：

```python
self.on_cloud_run = "K_SERVICE" in os.environ
self.dev_login = _bool(os.environ.get("DEV_LOGIN", "0")) and not self.on_cloud_run
```

就算有人不小心在雲端設了 `DEV_LOGIN=1`，開發模式登入也不會開。這叫**縱深防禦**：不靠單一設定保護。

### 依賴套件要釘版本

`requirements.txt` 寫 `fastapi==0.161.1` 而不是 `fastapi`。原因：雲端建置時會重新安裝套件，沒釘版本的話，哪天新版不相容，**同一份程式碼會突然建置失敗或行為改變**。

我們實際遇過：一開始憑記憶寫的舊版本號，在 Python 3.14 上裝不起來。做法是先裝最新版、確認能跑，再用 `pip freeze` 把實際版本寫回去。

### 先在本機跑通、跑測試

```bash
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m uvicorn app.main:app --reload --env-file .env --port 8010
```

本機沒跑通的東西，上雲端只會更難除錯。

---

## 2. 容器化：Dockerfile

### 為什麼要容器

雲端的機器沒裝你的 Python、沒裝你的套件。**容器映像檔（image）** 把「作業系統精簡版 + Python + 套件 + 你的程式 + 啟動指令」打包成一個不可變的檔案，到哪裡跑結果都一樣。Cloud Run 就是「給它一個 image，它幫你跑」的服務。

### 逐行解說

```dockerfile
FROM python:3.14-slim
```
基底映像：官方 Python 3.14 的精簡版 Linux。`slim` 比完整版小很多，建置與冷啟動都更快。版本跟本機一致，避免「本機可以、雲端不行」。

```dockerfile
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
```
- 不產生 `.pyc` 檔（容器裡沒用處）
- **不緩衝輸出**：`print` 和 log 立刻送出。沒有這行，Cloud Run 的 log 可能延遲或在當機時遺失。

```dockerfile
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
```
**先複製 requirements、裝套件，再複製程式碼**，順序是刻意的。Docker 會一層一層快取：只改程式碼時，「裝套件」那層沒變就直接用快取，建置快很多。如果先 `COPY . .` 再裝套件，每改一行程式都要重裝全部套件。

```dockerfile
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips="*"
```
這行最關鍵，每個參數都有原因：

| 參數 | 為什麼 |
|---|---|
| `exec` | 讓 uvicorn 成為主程序，Cloud Run 要關機時送的訊號才收得到，能正常收尾 |
| `--host 0.0.0.0` | 預設的 `127.0.0.1` 只接受容器內部連線，外面連不進來 |
| `--port ${PORT:-8080}` | **Cloud Run 用 `PORT` 環境變數告訴你要聽哪個埠**，不能自己決定 |
| `--proxy-headers` | 見下方說明 |
| `--forwarded-allow-ips="*"` | 信任前面那層 Google 代理送來的標頭 |

**`--proxy-headers` 為什麼重要：** 使用者用 `https` 連到 Google 前端，Google 解開加密後用 `http` 轉給你的容器。容器以為自己是 `http`，產生的網址也會是 `http://...`。Google 登入的回呼網址就會變成 `http://.../auth/callback`，跟你在 Google 登記的 `https://...` 不符，又是 `redirect_uri_mismatch`。加了這個參數，uvicorn 會讀 `X-Forwarded-Proto: https` 標頭，知道原本是 https。

### 排除不該上傳的檔案

`.gcloudignore`（上傳時排除）與 `.dockerignore`（建置時排除）內容一樣：

```
.venv/      ← 本機虛擬環境，Windows 專用、又大，容器裡會重裝
.env        ← 機密！絕不能上傳
*.db        ← 本機 SQLite 資料
tests/      ← 執行時用不到
```

漏掉 `.env` 是常見的資安事故：機密會被打包進 image，任何能讀 image 的人都看得到。

---

## 3. GCP 基本概念

| 概念 | 說明 |
|---|---|
| **專案 Project** | 所有資源、權限、帳單的容器。有兩個識別碼：**專案 ID**（`project-a79673e6-...`，人看的）和**專案編號**（`621748777623`，系統用的，服務帳號名稱裡會出現） |
| **帳單帳戶 Billing** | 就算全在免費額度內，多數服務也要求專案綁定帳單才能啟用 |
| **API／服務** | GCP 每個產品都是一個 API，預設關閉，要先「啟用」才能用 |
| **區域 Region** | 機房位置。`asia-east1` 在台灣，延遲最低 |
| **IAM** | 權限系統：**誰**（成員）對**什麼**（資源）有**什麼角色**（一組權限） |
| **服務帳號 Service Account** | 給「程式」用的帳號，不是給人用的。Cloud Run 和 Cloud Build 都以某個服務帳號的身分去存取其他服務 |

### 這次用到的服務帳號

```
621748777623-compute@developer.gserviceaccount.com
```

這是「Compute Engine 預設服務帳號」，格式是 `<專案編號>-compute@...`。在新專案裡，它同時是：
- **Cloud Run 執行時的身分**：容器讀 Secret Manager 時，用的就是它
- **Cloud Build 建置時的身分**：讀原始碼、推 image，也是它

所以第 6、8 節的權限都是加給它。

---

## 4. 準備 gcloud

`gcloud` 是 GCP 的命令列工具，網頁 Console 能做的事它幾乎都能做，而且可以寫成腳本重複執行。

```bash
winget install Google.CloudSDK          # 安裝（Windows）
gcloud auth login                       # 用瀏覽器登入你的 Google 帳號
gcloud config set project <專案 ID>      # 之後的指令預設都對這個專案
```

檢查目前狀態：

```bash
gcloud auth list      # 登入的是哪個帳號（前面有 * 的是使用中的）
gcloud config list    # 預設專案、帳號
```

> 裝完要**重開終端機**，新的 PATH 才會生效。

---

## 5. 啟用 API

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
```

| API | 在流程中的角色 |
|---|---|
| `run` | Cloud Run 本身：跑容器、給網址 |
| `cloudbuild` | 在雲端照 Dockerfile 建 image（你電腦不用裝 Docker） |
| `artifactregistry` | 存放 image |
| `secretmanager` | 存放機密值 |

上傳原始碼用的 Cloud Storage 預設已經啟用。

查專案編號（之後設權限要用）：

```bash
gcloud projects describe <專案 ID> --format="value(projectNumber)"
```

---

## 6. 機密值：Secret Manager

### 為什麼不直接用環境變數

`--set-env-vars` 設的值，任何能看 Cloud Run 設定的人都看得到明文，也會出現在部署紀錄裡。Secret Manager 則是：
- 加密儲存
- 有獨立的存取權限（誰能讀哪個 secret）
- 有**版本**：換密碼時新增一版，舊版保留，可以追蹤與回復

判斷原則：**洩漏了會出事的放 secret，其他放 env var。**

| 值 | 放哪裡 | 理由 |
|---|---|---|
| `DATABASE_URL` | secret | 內含資料庫密碼 |
| `SESSION_SECRET` | secret | 拿到就能偽造登入 cookie |
| `GOOGLE_CLIENT_SECRET` | secret | 拿到就能冒充你的網站換 token |
| `GOOGLE_CLIENT_ID` | env var | 本來就會出現在瀏覽器網址列，是公開的 |
| `ALLOWED_EMAILS`、`OBSIDIAN_VAULT` | env var | 不是機密 |

### 建立 secret

```bash
gcloud secrets create DATABASE_URL --replication-policy=automatic --data-file=-
```

`--data-file=-` 表示「從標準輸入讀」：執行後貼上值，按 Ctrl+Z、Enter（Windows）結束。這樣機密不會留在指令歷史裡。

> 這次我是用一支小腳本從 `.env` 讀值、直接餵給 gcloud，值完全沒有顯示在畫面上。原理一樣，都是走標準輸入。

之後要換值（例如重設資料庫密碼）：

```bash
gcloud secrets versions add DATABASE_URL --data-file=-
```

再部署一次就會讀到新版本，因為我們指定的是 `:latest`。

### 授權 Cloud Run 讀取

建好 secret 不代表 Cloud Run 讀得到，要明確授權。我們**只對這三個 secret 個別授權**，而不是整個專案：

```bash
gcloud secrets add-iam-policy-binding DATABASE_URL --member=serviceAccount:621748777623-compute@developer.gserviceaccount.com --role=roles/secretmanager.secretAccessor
```

（三個 secret 各做一次。）

這就是**最小權限原則**：服務帳號只拿到它需要的那幾把鑰匙。萬一將來專案裡多了別的 secret，這個網站也讀不到。

---

## 7. 部署：`gcloud run deploy` 背後發生什麼

### 指令

```bash
gcloud run deploy neuron \
  --source . \
  --region asia-east1 \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_CLIENT_ID=...,ALLOWED_EMAILS=lithium8578@gmail.com,OBSIDIAN_VAULT=Obsidian-Master" \
  --set-secrets "DATABASE_URL=DATABASE_URL:latest,SESSION_SECRET=SESSION_SECRET:latest,GOOGLE_CLIENT_SECRET=GOOGLE_CLIENT_SECRET:latest"
```

（PowerShell 不能用 `\` 換行，實際執行時寫成一行。）

| 參數 | 意義 |
|---|---|
| `neuron` | 服務名稱，也會出現在網址裡 |
| `--source .` | 從目前資料夾的原始碼建置（另一種是 `--image`，直接給現成 image） |
| `--region` | 部署到哪個機房 |
| `--allow-unauthenticated` | 允許任何人**連到**網站。「誰能**用**」由我們自己的 Google 登入把關。不加的話，連登入頁都打不開 |
| `--set-env-vars` | 一般環境變數 |
| `--set-secrets` | `環境變數名=secret名:版本`，執行時從 Secret Manager 讀出來，變成環境變數 |
| `--quiet` | 遇到「要不要建立 XX？」一律回答預設值，適合腳本 |

### 背後的五個階段

實際輸出對照：

```
Creating Container Repository....done     ← ① 第一次才有
Uploading sources....done                 ← ②
Building Container....done                ← ③
Setting IAM Policy....done                ← ④
Creating Revision....done                 ← ⑤
Routing traffic....done
Service URL: https://neuron-621748777623.asia-east1.run.app
```

**① 建立 Artifact Registry 儲存庫**
第一次部署時，自動建立一個叫 `cloud-run-source-deploy` 的儲存庫，之後所有 image 都放在這裡。

**② 上傳原始碼**
把資料夾（扣掉 `.gcloudignore` 排除的）壓成 zip，上傳到一個 Cloud Storage bucket：`run-sources-<專案ID>-asia-east1`。

**③ 建置 image**
Cloud Build 開一台臨時機器，下載 zip，照 Dockerfile 一步步執行，產出 image，推到：

```
asia-east1-docker.pkg.dev/<專案ID>/cloud-run-source-deploy/neuron@sha256:ca039e...
```

`@sha256:...` 是 image 內容的指紋，同樣的指紋保證是完全相同的 image。

**④ 設定 IAM**
因為加了 `--allow-unauthenticated`，把「`allUsers` 可以呼叫這個服務」寫進服務的權限。

**⑤ 建立 revision、切換流量**
**Revision** 是「某個 image + 某組設定」的不可變快照，名稱像 `neuron-00001-n26`。Cloud Run 先把新 revision 開起來、確認容器有在 `PORT` 上回應，健康了才把 100% 流量切過去。

這代表：
- **新版壞掉不會影響舊版**：啟動失敗的話，流量留在舊 revision，網站不中斷
- **可以秒回滾**：舊 revision 都還在（第 11 節）

我們目前有兩個 revision：`00001`（第一次部署）和 `00002`（把 `/healthz` 改成 `/health` 那次）。

### 預設的執行規格

```
CPU: 1 vCPU    記憶體: 512 MiB    最多 20 台    閒置時 0 台
```

閒置時縮到 0 台，就是「不用不花錢」的原因，代價是冷啟動（第 12 節）。

---

## 8. 我們遇到的權限錯誤（IAM 實戰）

第一次部署失敗：

```
ERROR: (gcloud.run.deploy) INVALID_ARGUMENT: Invalid build request. could not resolve source:
googleapi: Error 403: 621748777623-compute@developer.gserviceaccount.com does not have
storage.objects.get access to the Google Cloud Storage object. ...
```

### 怎麼讀這個錯誤

拆開來看，錯誤訊息其實把答案講完了：

| 片段 | 意思 |
|---|---|
| `Invalid build request` | 卡在第 ③ 階段，建置 |
| `621748777623-compute@...` | **誰**：建置用的服務帳號 |
| `storage.objects.get` | **缺什麼權限**：讀 Cloud Storage 物件 |
| `.../run-sources-.../neuron/....zip` | **對什麼資源**：第 ② 階段上傳的那個 zip |

也就是：原始碼上傳成功了，但建置機器沒有權限把它讀回來。

### 為什麼會這樣

Google 為了安全，從 2024 年起，**新專案的預設服務帳號不再自動擁有大範圍權限**。舊教學沒提這一步，因為以前的專案不需要。

### 解法

給它 **Cloud Run Builder** 角色。這是 Google 為「從原始碼部署到 Cloud Run」設計的角色，剛好包含讀原始碼、寫 log、推 image 等權限：

```bash
gcloud projects add-iam-policy-binding <專案ID> --member="serviceAccount:621748777623-compute@developer.gserviceaccount.com" --role="roles/run.builder"
```

加完重跑部署就成功了。

### 通用除錯方法

遇到 403／permission denied，照這三問找答案：
1. **誰**在做事？（哪個帳號或服務帳號）
2. 缺**哪個權限**？（`xxx.yyy.zzz` 格式）
3. 對**哪個資源**？

然後找一個「包含該權限、又不會給太多」的角色。優先用 Google 為該情境設計的角色（像 `run.builder`），不要直接給 `Owner` 或 `Editor`。

---

## 9. 上線後的 Google 登入設定

部署完才知道正式網址，所以要回 Google Cloud Console → **APIs & Services → Credentials → 你的 OAuth client**，在 **Authorized redirect URIs** 新增：

```
https://neuron-621748777623.asia-east1.run.app/auth/callback
```

本機的 `http://localhost:8010/auth/callback` 保留，兩個並存，本機與線上都能登入。

OAuth 的原理見對話紀錄，重點一句：**Google 只會把授權碼送到事先登記過的網址**，防止別人拿你的 client ID 架假網站偷授權碼。所以每多一個網址（例如將來換自訂網域）都要來這裡登記。

---

## 10. 驗證上線結果

部署成功不等於網站正常。每次上線後，用 `curl` 檢查幾個關鍵行為：

```bash
U=https://neuron-621748777623.asia-east1.run.app

curl -s $U/health
# 預期：{"ok":true}  → 容器有在跑

curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' $U/
# 預期：303 .../login  → 沒登入會被擋

curl -s -o /dev/null -w '%{http_code}\n' -X POST -d '' $U/auth/dev
# 預期：404  → 開發模式登入在雲端確實關閉

curl -s -o /dev/null -D - $U/auth/google | grep -i location
# 預期：redirect_uri=https://.../auth/callback  → 是 https，--proxy-headers 有生效

curl -s -o /dev/null -D - $U/auth/google | grep -i set-cookie
# 預期：含 secure、samesite=lax、httponly  → cookie 安全設定正確
```

### 這次驗證抓到的兩件事

1. **`/healthz` 回傳 Google 的 404 頁面**，而不是我們的程式。原因：Cloud Run 保留了一些以 `z` 結尾的路徑給自己用，請求根本到不了容器。解法是改名成 `/health`。這種事只有實際上線測試才會發現。
2. **POST 測試一開始拿到 411**（Length Required）。原因是 `curl -X POST` 沒帶內容，Google 前端要求 POST 一定要有 `Content-Length`。加上 `-d ''` 送出空內容就正常回 404。這是測試方法的問題，不是網站的問題。**看到奇怪的結果，先確認是測試方法還是程式的問題。**

---

## 11. 日常維運：更新、看 log、回滾

### 更新網站

改完程式、本機測試通過後：

```bash
gcloud run deploy neuron --source . --region asia-east1
```

環境變數和 secrets 會沿用上一個 revision，不用重打。

### 看 log

```bash
gcloud run services logs read neuron --region asia-east1 --limit 50
```

或到 Console → Cloud Run → neuron → **Logs**，可以篩選錯誤等級。程式裡的 `print` 和 uvicorn 的請求紀錄都會在這裡，這也是 Dockerfile 要設 `PYTHONUNBUFFERED=1` 的原因。

### 查看與回滾 revision

```bash
gcloud run revisions list --service neuron --region asia-east1
```

新版有問題、想立刻退回舊版：

```bash
gcloud run services update-traffic neuron --region asia-east1 --to-revisions neuron-00001-n26=100
```

不用重新建置，幾秒內完成。修好之後正常部署，新 revision 會再接手流量。

### 查看目前設定

```bash
gcloud run services describe neuron --region asia-east1
```

### 換機密值

```bash
gcloud secrets versions add SESSION_SECRET --data-file=-
gcloud run deploy neuron --source . --region asia-east1
```

（換 `SESSION_SECRET` 會讓所有人登出，因為舊 cookie 的簽章對不上了。）

---

## 12. 費用與效能

### 費用

這種一人使用的網站，正常情況下每個月接近 0 元：
- **Cloud Run**：只在處理請求時計費，閒置縮到 0 台不收錢。每月有免費額度（請求數、CPU 秒數、記憶體秒數）。
- **Cloud Build**：每月有免費建置分鐘數，一次建置大約 1–3 分鐘。
- **Artifact Registry**：每次部署會多存一個 image，有少量免費儲存空間。久了可以到 Console 刪掉舊 image。
- **Secret Manager**：少量 secret 與存取次數在免費額度內。
- **Neon**：免費方案 0.5 GB，幾百筆筆記用不到 1%。

確切額度以各服務的官方定價頁為準。建議到 Billing → **Budgets & alerts** 設一個小額預算警示（例如 1 美元），超過就寄信通知。

### 冷啟動

閒置一段時間後第一次打開會比較慢，因為要：
1. Cloud Run 開一台新容器、啟動 Python、載入套件（約 1–2 秒）
2. Neon 從休眠中喚醒資料庫（約 0.5–1 秒）

之後的請求就很快。如果很在意，可以讓 Cloud Run 永遠保留 1 台，但**閒置時也會計費**：

```bash
gcloud run services update neuron --region asia-east1 --min-instances 1
```

一個人用的話，建議接受冷啟動。

### 延遲

容器在台灣（asia-east1），Neon 在新加坡，每次查詢多大約幾十毫秒的來回。Neon 沒有台灣機房，新加坡是最近的選擇。

---

## 13. 疑難排解

| 症狀 | 在哪一段 | 原因與解法 |
|---|---|---|
| `storage.objects.get` 403 | ③ 建置 | 新專案的建置服務帳號缺權限，給 `roles/run.builder`（第 8 節） |
| 建置失敗、`pip install` 報錯 | ③ 建置 | 套件版本與 Python 版本不相容。本機用同版 Python 先裝一次，`pip freeze` 釘版本 |
| `Container failed to start ... PORT` | ⑤ revision | 程式沒聽 `$PORT` 或 host 不是 `0.0.0.0`。檢查 Dockerfile 的 `CMD` |
| 啟動失敗，log 有 `SESSION_SECRET` | ⑤ revision | secret 沒設好。我們的程式在 Cloud Run 上缺 `SESSION_SECRET` 會故意拒絕啟動 |
| `Permission denied on secret` | ⑤ revision | 服務帳號沒有 `secretAccessor`（第 6 節） |
| 部署成功但網頁 500 | 執行中 | 看 log（第 11 節），通常是資料庫連線字串錯誤或網路問題 |
| `redirect_uri_mismatch` | 登入 | 正式網址沒登記到 OAuth client（第 9 節），或缺 `--proxy-headers` 導致網址是 http |
| 某個路徑回傳 Google 的 404 頁 | 路由 | 撞到 Cloud Run 保留路徑（如 `/healthz`），改名 |
| POST 回 411 | 測試方法 | curl 要加 `-d ''` |
| 第一次打開很慢 | 正常 | 冷啟動（第 12 節） |

**除錯的基本動作**：先從輸出判斷卡在哪個階段（上傳／建置／啟動／執行），再去對應的地方看詳細 log：
- 建置失敗：輸出會給 Cloud Build 的 log 網址
- 啟動或執行失敗：Cloud Run 的 Logs 分頁

---

## 14. 名詞表

| 名詞 | 白話解釋 |
|---|---|
| **容器 / image** | 把程式和它需要的一切打包成一個檔案，在哪跑都一樣 |
| **Dockerfile** | 製作 image 的食譜 |
| **revision** | Cloud Run 上「某版 image + 某組設定」的快照，不可修改，可以切換流量 |
| **冷啟動** | 從 0 台開出第一台容器的等待時間 |
| **服務帳號** | 給程式用的帳號，程式用它的身分去存取其他雲端服務 |
| **IAM 角色** | 一組權限的集合，例如 `secretAccessor` = 可以讀 secret |
| **最小權限原則** | 只給剛好夠用的權限，出事時損害最小 |
| **反向代理** | 擋在你的程式前面、代為接收請求的伺服器。這裡是 Google 前端，負責 HTTPS |
| **TLS 終止** | 在代理那層解開 HTTPS 加密，之後用 HTTP 轉給你的程式 |
| **環境變數** | 作業系統給程式的設定值，用來讓同一份程式在不同環境有不同行為 |
| **12-Factor App** | 一套雲端應用程式的設計原則，「設定放環境變數」是其中一條 |

---

## 延伸學習方向

1. **自動部署（CI/CD）**：用 GitHub Actions，push 到 main 就自動測試＋部署，跟晨報同一套工具
2. **資料表遷移（Alembic）**：目前是啟動時自動建表，之後要改欄位時需要
3. **自訂網域**：把網址換成自己的網域
4. **在本機用 Docker 跑同一個 image**：更貼近雲端環境，部署前先抓問題
