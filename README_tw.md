# Labels Service (標籤列印服務)

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.118.0-009688?logo=fastapi&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![Linux](https://img.shields.io/badge/Platform-Linux-FCC624?logo=linux&logoColor=black)
![pytest](https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest)
![MIT License](https://img.shields.io/badge/License-MIT-green.svg)

使用 **FastAPI** 整合 **gLabels** 的標籤列印微服務。  
提供 REST API 將 **JSON → CSV → gLabels 模板 → PDF**，支援非同步任務處理、平行執行、逾時處理與檔案下載。

📖 **[English Version README](README.md)**

## 快速開始

```bash
# 1. 複製環境設定檔
cp .env.example .env

# 2. 使用 Docker Compose 啟動
docker compose up -d

# 3. 開啟 API 文件
open http://localhost:8000/docs
```

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

## Docker 部署

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
docker build -t labels-service .

# 2. 建立目錄 (請依需求調整路徑)
mkdir -p /your/path/output /your/path/templates
# mkdir -p /your/path/temp  # 只有當 .env 中 KEEP_CSV=true 時才需要

# 3. 使用 .env 檔案執行容器
docker run -d \
  --name labels-service \
  -p 8000:8000 \
  --env-file .env \
  -v /your/path/output:/app/output \
  -v /your/path/templates:/app/templates \
  --restart unless-stopped \
  labels-service
  # 只有當 KEEP_CSV=true 時才需要掛載 temp 目錄：
  # -v /your/path/temp:/app/temp \
```

#### 方法 B：使用環境變數參數

```bash
# 1. 建置映像檔
docker build -t labels-service .

# 2. 建立目錄 (請依需求調整路徑)
mkdir -p /your/path/output /your/path/templates
# mkdir -p /your/path/temp  # 只有當 KEEP_CSV=true 時才需要

# 3. 使用環境變數參數執行容器
docker run -d \
  --name labels-service \
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
  labels-service
  # 如果要保留 CSV 檔案，請設定 KEEP_CSV=true 並掛載 temp 目錄：
  # -e KEEP_CSV=true \
  # -v /your/path/temp:/app/temp \

# 4. 檢查日誌
docker logs -f labels-service

# 5. 存取 API 文件
open http://localhost:8000/docs
```

**停止與清理：**

```bash
docker stop labels-service
docker rm labels-service
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
GLABELS_TIMEOUT=600         # 單一任務逾時秒數
RETENTION_HOURS=24          # 任務保存時數
LOG_LEVEL=INFO              # 日誌等級
```

## 本機開發

**注意**: 本機開發需要 Linux 或 WSL2 環境，因為 gLabels 僅支援 Linux 平台。

```bash
# 建立虛擬環境
python -m venv venv
source venv/bin/activate

# 安裝相依套件
pip install -r requirements.txt

# 安裝開發相依套件 (測試與程式碼品質工具)
pip install -r requirements-dev.txt

# 在 Linux 系統上安裝 gLabels (必要相依軟體)
sudo apt-get install glabels glabels-data fonts-dejavu fonts-noto-cjk

# 執行應用程式
python -m app.main
```

### VS Code 偵錯 (F5)

專案已包含 `.vscode/launch.json` 偵錯配置。直接按 **F5** 即可開始偵錯，支援中斷點功能。

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

### 列出模板

```bash
curl http://localhost:8000/labels/templates
```

## 模板與資料格式

- 將 `.glabels` 模板檔案放置於 `templates/` 目錄
- JSON 資料欄位必須與模板變數對應
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
docker compose exec label-service sh
```

## 部署建議

- 定期備份 `templates/` 和 `output/` 目錄
- 監控容器資源使用狀況
- 日誌自動輪轉 (5MB/檔案, 保留10個檔案)，可在 `app/core/logger.py` 調整

## 設定說明

- `MAX_PARALLEL=0` 自動設定為 CPU 核心數-1，可根據系統效能調整
- `MAX_LABELS_PER_BATCH=300` 控制每批次處理的標籤數量，超過時會自動分批處理再合併為單一 PDF
- `GLABELS_TIMEOUT=600` 如果處理大量資料時逾時，可適當提高
- `KEEP_CSV=true` 開啟可保留中繼 CSV 檔案供偵錯檢查
- `RETENTION_HOURS=24` 控制任務在記憶體中保存的時間
