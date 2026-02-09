# gLabels Batch Service (標籤列印服務)

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.118.0-009688?logo=fastapi&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![Linux](https://img.shields.io/badge/Platform-Linux-FCC624?logo=linux&logoColor=black)
![pytest](https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest)
![MIT License](https://img.shields.io/badge/License-MIT-green.svg)

使用 **FastAPI** 整合 **gLabels** 的標籤列印微服務。  
提供 REST API 將 **JSON → CSV → gLabels 模板 → PDF**，支援非同步任務處理、平行執行、逾時處理與檔案下載。

**[English Version README](README.md)**

## 快速開始

```bash
# 1. 複製環境設定檔
cp .env.example .env

# 2. 使用 Docker Compose 啟動
docker compose up -d

# 3. 開啟 API 文件
open http://localhost:8000/docs
```

## 快速開始（開發模式）

### 選項一：原生開發（Linux/Mac/WSL）

**系統需求：**
- Python 3.12
- Linux 或 WSL2（gLabels 僅支援 Linux）

```bash
# 1. 複製環境設定模板
cp .env.example .env

# 2. 設定虛擬環境
python -m venv venv
source venv/bin/activate

# 3. 安裝依賴套件
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 4. 安裝 gLabels
sudo apt-get install glabels glabels-data fonts-dejavu fonts-noto-cjk

# 5. 使用 uvicorn 執行（啟用自動重載）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 或在 VS Code 中按 F5 進行除錯
```

### 選項二：Docker 開發（Windows/跨平台）

```bash
# 1. 複製環境設定模板
cp .env.example .env

# 2. 使用 Docker Compose 啟動（啟用熱重載）
docker compose up -d

# 3. 查看日誌
docker compose logs -f

# 4. 開啟 API 文件
open http://localhost:8000/docs
```

開發環境設定包含：
- 程式碼變更時自動重載（透過 `--reload` 旗標或掛載 ./app 目錄）
- 除錯級別的日誌記錄
- 保留 CSV 檔案以便除錯

---

## 正式環境部署

### 方法一：使用環境變數（建議）

在您的部署平台（Kubernetes、AWS ECS 等）設定環境變數：

```bash
# 建置映像檔
docker build -t glabels-batch-service:latest .

# 使用環境變數執行
docker run -d \
  --name glabels-batch-service \
  -p 8000:8000 \
  -e ENVIRONMENT=production \
  -e RELOAD=false \
  -e LOG_LEVEL=WARNING \
  -e KEEP_CSV=false \
  -e MAX_PARALLEL=4 \
  -v /data/output:/app/output \
  -v /data/templates:/app/templates \
  -v /data/logs:/app/logs \
  --restart always \
  glabels-batch-service:latest
```

### 方法二：使用 compose.prod.yml

```bash
# 1. 在系統或 CI/CD 中設定環境變數
export ENVIRONMENT=production
export LOG_LEVEL=WARNING
export MAX_PARALLEL=4
# ... 其他設定

# 2. 啟動正式環境服務
docker compose -f compose.prod.yml up -d

# 3. 檢查狀態
docker compose -f compose.prod.yml ps
docker compose -f compose.prod.yml logs -f
```

### 正式環境檢查清單

部署到正式環境前，請確認：

- [ ] 已設定 `ENVIRONMENT=production`
- [ ] `RELOAD=false`（關鍵設定 - 若為 true 將無法通過驗證）
- [ ] `LOG_LEVEL` 設為 WARNING 或 ERROR
- [ ] `KEEP_CSV=false`（節省磁碟空間）
- [ ] 根據可用 CPU 核心數設定 `MAX_PARALLEL`
- [ ] 正確設定 `/app/output`、`/app/templates`、`/app/logs` 的磁碟區掛載
- [ ] 為 `/health` 端點設定監控
- [ ] 設定資源限制（CPU/記憶體）
- [ ] 使用密鑰管理工具管理敏感設定
- [ ] **絕不將 .env.production 提交至 git** - 請使用系統環境變數

---

## 設定檔載入優先順序

設定檔按以下順序載入（後者覆蓋前者）：

1. **預設值** 定義於 `app/config.py`
2. **`.env` 檔案**（若存在）- 用於開發環境
3. **系統環境變數** - 建議用於正式環境

範例：
```bash
# .env 檔案中設定：LOG_LEVEL=DEBUG
# 系統環境變數：export LOG_LEVEL=WARNING
# 結果：LOG_LEVEL=WARNING（系統環境變數優先）
```

---

## 環境設定檔說明

| 檔案 | 用途 | 是否提交至 Git？ |
|------|------|-----------------|
| `.env.example` | 開發環境模板 | ✅ 是 |
| `.env.production.example` | 正式環境模板 | ✅ 是 |
| `.env` | 開發環境設定 | ❌ 否 |
| `.env.production` | 正式環境設定 | ❌ 否 |
| `.env.local` | 本地覆寫設定 | ❌ 否 |

---

## 安全性注意事項

**重要：** 絕不將包含實際值的環境設定檔（`.env`、`.env.production`）提交至版本控制系統。

- `.env.example` 和 `.env.production.example` 是安全的範本檔案
- `compose.prod.yml` 使用 `${VAR:-default}` 語法從系統環境載入變數
- 正式環境建議使用系統環境變數而非 `.env` 檔案
- 應用程式會驗證在正式環境模式下 `RELOAD=false`

---

## 架構說明

```text
客戶端請求 → FastAPI → 工作管理器 → 模板服務 → gLabels引擎 → PDF輸出
                      ↓           ↓          ↓
                  非同步佇列   模板探索    CLI封裝器
```

## 專案結構

```text
app/
├── api/           # API 路由與端點
├── core/          # 日誌與版本資訊
├── parsers/       # 模板格式解析器
├── services/      # 業務邏輯 (JobManager, TemplateService)
├── utils/         # GlabelsEngine CLI 封裝器
├── config.py      # 環境設定
├── schema.py      # Pydantic schema 模型
└── main.py        # FastAPI 應用程式入口
```

## 系統需求

- **Linux 平台** (gLabels 僅支援 Linux)
- **Windows 使用者**: 請使用 WSL2 或 Docker Desktop
- Docker 與 Docker Compose
- gLabels 軟體 (Docker 容器中自動安裝)

## Docker 部署（其他方法）

**注意：** 快速開始請參閱上方章節。本節提供其他 Docker 部署方法。

### 方案一：Docker Compose (建議)

```bash
# 1. 複製環境設定模板
cp .env.example .env

# 2. 建置並啟動
docker compose up -d

# 3. 檢查狀態
docker compose ps
docker compose logs -f

# 4. 存取 API 文件
open http://localhost:8000/docs
```

### 方案二：純 Dockerfile

#### 方法 A：使用 .env 檔案

```bash
# 1. 複製環境範本並建置映像檔
cp .env.example .env
docker build -t glabels-batch-service .

# 2. 建立目錄 (請依需求調整路徑)
mkdir -p /your/path/output /your/path/templates
# mkdir -p /your/path/temp  # 只有當 .env 中 KEEP_CSV=true 時才需要

# 3. 使用 .env 檔案執行容器
docker run -d \
  --name glabels-batch-service \
  -p 8000:8000 \
  --env-file .env \
  -v /your/path/output:/app/output \
  -v /your/path/templates:/app/templates \
  --restart unless-stopped \
  glabels-batch-service
  # 只有當 KEEP_CSV=true 時才需要掛載 temp 目錄：
  # -v /your/path/temp:/app/temp \
```

#### 方法 B：使用環境變數參數

```bash
# 1. 建置映像檔
docker build -t glabels-batch-service .

# 2. 建立目錄 (請依需求調整路徑)
mkdir -p /your/path/output /your/path/templates
# mkdir -p /your/path/temp  # 只有當 KEEP_CSV=true 時才需要

# 3. 使用環境變數參數執行容器
docker run -d \
  --name glabels-batch-service \
  -p 8000:8000 \
  -e HOST=0.0.0.0 \
  -e PORT=8000 \
  -e LOG_LEVEL=INFO \
  -e KEEP_CSV=false \
  -e MAX_PARALLEL=0 \
  -e GLABELS_TIMEOUT=600 \
  -e RETENTION_HOURS=24 \
  -v /your/path/output:/app/output \
  -v /your/path/templates:/app/templates \
  --restart unless-stopped \
  glabels-batch-service
  # 如果要保留 CSV 檔案，請設定 KEEP_CSV=true 並掛載 temp 目錄：
  # -e KEEP_CSV=true \
  # -v /your/path/temp:/app/temp \

# 4. 檢查日誌
docker logs -f glabels-batch-service

# 5. 存取 API 文件
open http://localhost:8000/docs
```

**停止與清理：**

```bash
docker stop glabels-batch-service
docker rm glabels-batch-service
```

## 環境變數設定

將 `.env.example` 複製為 `.env` 並依需求調整：

```bash
HOST=0.0.0.0                # 伺服器位址
PORT=8000                   # 伺服器埠號
RELOAD=false                # 自動重載 (開發用)
KEEP_CSV=false              # 保留中繼 CSV 檔案
MAX_PARALLEL=0              # 最大平行工作數 (0=自動)
MAX_LABELS_PER_BATCH=300    # 每批最大標籤數量
MAX_LABELS_PER_JOB=2000     # 單次請求最大標籤數量
GLABELS_TIMEOUT=600         # 單一任務逾時秒數
RETENTION_HOURS=24          # 任務保存時數
LOG_LEVEL=INFO              # 日誌等級
MAX_REQUEST_BYTES=5000000   # 最大請求 body bytes
MAX_FIELDS_PER_LABEL=50     # 單筆最大欄位數量
MAX_FIELD_LENGTH=2048       # 單一欄位最大字元長度
CORS_ALLOW_ORIGINS=
```

## 本地開發

詳細的本地開發設定說明請參閱上方的 **[快速開始（開發模式）](#快速開始開發模式)** 章節。

## API 使用範例

### 提交列印任務

```bash
curl -X POST http://localhost:8000/labels/print \
  -H "Content-Type: application/json" \
  -d '{
    "template_name": "demo.glabels",
    "data": [
      {"CODE": "A001", "ITEM": "產品 A"},
      {"CODE": "A002", "ITEM": "產品 B"}
    ],
    "copies": 1
  }'
```

回應：

```json
{"job_id": "abc123..."}
```

### 查詢任務狀態

```bash
curl http://localhost:8000/labels/jobs/abc123...
```

### 即時狀態推送 (SSE)

使用 Server-Sent Events 獲取即時狀態更新：

```bash
curl -N http://localhost:8000/labels/jobs/abc123.../stream
```

或在 JavaScript 中使用：

```javascript
const es = new EventSource('/labels/jobs/abc123.../stream');
es.addEventListener('status', (e) => {
    const job = JSON.parse(e.data);
    console.log(job.status);  // pending → running → done
    if (job.status === 'done' || job.status === 'failed') {
        es.close();
    }
});
```

### 下載 PDF

```bash
curl -O http://localhost:8000/labels/jobs/abc123.../download
```

瀏覽器預覽：

```bash
curl http://localhost:8000/labels/jobs/abc123.../download?preview=true
```

### 列出模板

```bash
curl http://localhost:8000/labels/templates
```

## 模板與資料格式

- 將 `.glabels` 模板檔案放置於 `templates/` 目錄
- JSON 資料欄位必須與模板變數對應
- data 陣列不得為空，且需符合設定的上限
- 產生的 PDF 儲存至 `output/` 目錄
- 暫存 CSV 檔案位於 `temp/` (可設定保留與否)

## 測試

```bash
# 執行所有測試
pytest tests/

# 詳細輸出
pytest tests/ -v

# 生成覆蓋率報告
pytest tests/ --cov=app --cov-report=html

# 執行特定測試
pytest tests/test_glabels_engine.py
```

## 疑難排解

**常見問題：**

- `404 Job not found` - 任務已過期或不存在
- `glabels-3-batch not found` - gLabels 未安裝 (Docker 中不應發生)
- 權限錯誤 - 檢查目錄掛載權限
- 找不到模板 - 確認模板存在於 `templates/` 目錄
- **Windows 相容性** - 請使用 Docker Desktop 或 WSL2 (gLabels 需要 Linux)

**除錯方法：**

```bash
# 檢查容器日誌
docker compose logs -f

# 檢查容器狀態
docker compose ps

# 進入容器 shell
docker compose exec glabels-batch-service sh
```

## 部署建議

- 定期備份 `templates/` 和 `output/` 目錄
- 監控容器資源使用狀況
- 日誌自動輪轉 (5MB/檔案, 保留10個檔案)，可在 `app/core/logger.py` 調整

## 設定說明

- `MAX_PARALLEL=0` 自動設定為 CPU 核心數-1，可根據系統效能調整
- `MAX_LABELS_PER_BATCH=300` 控制每批次處理的標籤數量，超過時會自動分批處理再合併為單一 PDF
- `MAX_LABELS_PER_JOB=2000` 控制單次請求最多可處理的標籤數量
- `MAX_REQUEST_BYTES=5000000` 限制請求 body 大小以避免記憶體壓力
- `MAX_FIELDS_PER_LABEL=50` 限制單筆資料欄位數量
- `MAX_FIELD_LENGTH=2048` 限制單一欄位字串長度
- `CORS_ALLOW_ORIGINS` 允許的來源清單（留空即關閉 CORS）
- `GLABELS_TIMEOUT=600` 如果處理大量資料時逾時，可適當提高
- `KEEP_CSV=true` 開啟可保留中繼 CSV 檔案供偵錯檢查
- `RETENTION_HOURS=24` 控制任務在記憶體中保存的時間
