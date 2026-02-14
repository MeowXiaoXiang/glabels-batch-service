# gLabels Batch Service

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.128.6-009688?logo=fastapi&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![Linux](https://img.shields.io/badge/Platform-Linux-FCC624?logo=linux&logoColor=black)
![pytest](https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest)
![MIT License](https://img.shields.io/badge/License-MIT-green.svg)

使用 **FastAPI** 整合 **gLabels** 的標籤列印微服務。將 **JSON → CSV → gLabels 模板 → PDF**，支援非同步任務、平行處理、逾時控制。

**[English Version README](README.md)**

---

## 快速開始

```bash
# 1. 複製環境設定
cp .env.example .env

# 2. 啟動服務（docker compose 會讀取 .env）
docker compose up -d

# 3. 開啟 API 文件
http://localhost:8000/docs
```

## 核心功能

- **批次列印**：JSON 資料批次轉換為 PDF 標籤
- **非同步處理**：任務佇列與背景執行
- **即時狀態**：SSE (Server-Sent Events) 即時推送
- **自動分批**：大量標籤自動分批處理與合併
- **模板管理**：自動探索與解析 `.glabels` 模板

## 安裝方式

### Docker（推薦）

說明：

- Docker 部署使用 `compose.yml`。
- 若沒有 `.env`，請先由 `.env.example` 複製。
- 啟動指令請參考上方「快速開始」。

### 原生安裝（Linux/WSL）

```bash
# 安裝依賴
sudo apt-get install glabels glabels-data fonts-dejavu fonts-noto-cjk
pip install -r requirements.txt

# 執行
uvicorn app.main:app --reload
```

> **Windows 使用者**：gLabels 僅支援 Linux，請使用 Docker 或 WSL2

---

## API 使用範例

### 提交列印任務

```bash
curl -X POST http://localhost:8000/labels/print \
  -H "Content-Type: application/json" \
  -d '{
    "template_name": "demo.glabels",
    "data": [
      {"CODE": "A001", "ITEM": "產品A"},
      {"CODE": "A002", "ITEM": "產品B"}
    ],
    "copies": 1
  }'
```

**回應：**

```json
{"job_id": "abc123..."}
```

### 查詢任務狀態

```bash
curl http://localhost:8000/labels/jobs/{job_id}
```

**回應範例：**

```json
{
  "job_id": "abc123...",
  "status": "done",
  "template": "demo.glabels",
  "filename": "demo_20260209_103000.pdf",
  "error": null,
  "created_at": "2026-02-09T10:30:00",
  "started_at": "2026-02-09T10:30:01",
  "finished_at": "2026-02-09T10:30:05"
}
```

### 即時狀態推送（SSE）

使用 Server-Sent Events 獲取即時狀態更新：

```bash
curl -N http://localhost:8000/labels/jobs/{job_id}/stream
```

**JavaScript 範例：**

```javascript
const es = new EventSource('/labels/jobs/{job_id}/stream');
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
# 下載檔案
curl -O http://localhost:8000/labels/jobs/{job_id}/download

# 瀏覽器預覽
curl http://localhost:8000/labels/jobs/{job_id}/download?preview=true
```

### 列出可用模板

```bash
curl http://localhost:8000/labels/templates
```

**回應範例：**

```json
[
  {
    "name": "demo.glabels",
    "field_count": 2,
    "has_headers": true
  }
]
```

---

## 環境變數設定

複製 `.env.example` 為 `.env` 並依需求調整：

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `ENVIRONMENT` | 執行環境 (development/production) | `production` |
| `HOST` / `PORT` | 伺服器位址與埠號 | `0.0.0.0` / `8000` |
| `RELOAD` | 程式碼變更時自動重載（僅開發） | `false` |
| `MAX_PARALLEL` | 平行工作數 (0=自動，支援 cgroup 偵測) | `0` |
| `MAX_LABELS_PER_BATCH` | 單批最大標籤數（超過自動分批） | `300` |
| `MAX_LABELS_PER_JOB` | 單次請求最大標籤數 | `2000` |
| `GLABELS_TIMEOUT` | 單批次處理逾時秒數 | `600` |
| `RETENTION_HOURS` | 任務保存時數 | `24` |
| `LOG_LEVEL` | 日誌等級 (DEBUG/INFO/WARNING/ERROR) | `INFO` |
| `LOG_FORMAT` | 日誌格式 (text/json) | `text` |
| `LOG_DIR` | 日誌檔案目錄 | `logs` |
| `REQUEST_ID_HEADER` | Request ID Header 名稱 | `X-Request-ID` |
| `RATE_LIMIT` | `/labels/print` 的速率限制 | `60/minute` |
| `ENABLE_METRICS` | 啟用 Prometheus metrics 端點 | `true` |
| `SHUTDOWN_TIMEOUT` | Graceful shutdown 逾時秒數 | `30` |
| `KEEP_CSV` | 保留中繼 CSV 檔案（除錯用） | `false` |
| `MAX_REQUEST_BYTES` | 請求 body 大小上限 | `5000000` |
| `MAX_FIELDS_PER_LABEL` | 單筆資料最大欄位數 | `50` |
| `MAX_FIELD_LENGTH` | 單一欄位最大長度 | `2048` |
| `CORS_ALLOW_ORIGINS` | 允許的來源清單（逗號分隔，留空關閉） | `` |

### 設定檔優先順序

設定按以下順序載入（後者覆蓋前者）：

1. 系統環境變數
2. `.env` 檔案
3. `app/config.py` 預設值

> **安全提醒**：絕不將包含實際值的 `.env` 提交至版本控制。

---

## 正式環境部署

本專案以內網部署為主。正式環境建議使用以下兩種流程：

1. 由 Linux service 指定環境變數（`Environment=` / `EnvironmentFile=`）。
2. 先匯入 `.env`，再啟動服務（減少手動輸入）。

接著使用 Docker Compose 啟動：

```bash
docker compose up -d
docker compose ps
docker compose logs -f
```

### 使用 nginx（反向代理）

若在 nginx 後方部署，請設定以下參數以支援 SSE：

```nginx
upstream backend {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 80;
    server_name example.com;

    # SSE 端點（即時推送）
    location /labels/jobs/ {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        
        # 關閉 buffering 以支援 Server-Sent Events
        proxy_buffering off;
        proxy_cache off;
        
        # 保持連線開啟以支援長期連線
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        
        # 必要的 headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        
        # CORS（optional，若需要）
        add_header Access-Control-Allow-Origin * always;
    }

    # 其他端點（一般 buffering）
    location / {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        
        proxy_buffering on;
        proxy_read_timeout 60s;
        
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
    }
}
```

**關鍵設定點**：

- `proxy_buffering off` — SSE 正常運作的必要條件
- `proxy_read_timeout 3600s` — 允許最多 1 小時的長期運行任務
- `proxy_http_version 1.1` — 連線重用的必要條件
- `Connection ""` — 防止 nginx 加入 `Connection: close`

> **提示**：若使用 SSL/TLS，請確保 `proxy_set_header X-Forwarded-Proto $scheme;` 被設定，以便應用知道它在 HTTPS 後方運行。

---

## 常見問題

**Q: Windows 可以用嗎？**  
A: gLabels 僅支援 Linux，請使用 Docker Desktop 或 WSL2

**Q: 任務一直顯示 pending？**  
A: 檢查 `docker compose logs -f` 確認 worker 是否正常運行，或檢查 `MAX_PARALLEL` 設定

**Q: 找不到模板？**  
A: 確認 `.glabels` 檔案在 `templates/` 目錄且副檔名正確，使用 `/labels/templates` API 列出可用模板

**Q: PDF 下載返回 404？**  
A: 任務可能已過期（預設 24 小時後清除），或任務尚未完成（檢查狀態是否為 `done`）

**Q: 返回 409 Conflict？**  
A: 任務仍在執行中，請等待完成後再下載

**Q: 如何調整平行處理數？**  
A: 設定 `MAX_PARALLEL`，`0` 為自動（CPU-1），或明確指定如 `4`；生產環境建議根據 CPU 核心數調整

**Q: 如何處理大量標籤？**  
A: 系統會自動分批處理（預設 300 張/批），設定調整 `MAX_LABELS_PER_BATCH`；最終 PDF 會自動合併

**Q: 逾時錯誤？**  
A: `GLABELS_TIMEOUT` 是**單批次**的逾時時間（預設 600 秒）。如處理 1000 張標籤分成 4 批，總時間可達 2400 秒。增加此值可處理更複雜的單批標籤

**除錯方法：**

```bash
# 查看容器日誌
docker compose logs -f

# 檢查容器狀態
docker compose ps

# 進入容器檢查
docker compose exec glabels-batch-service sh

# 檢查健康狀態
curl http://localhost:8000/health

# 檢查執行資訊
curl http://localhost:8000/
```

---

## 可觀測性

### Request ID

每個回應都包含 `X-Request-ID` header。可在請求時帶入自定 ID，或由伺服器自動產生。用於在 log 中追蹤完整請求流程。

### 速率限制

`/labels/print` 套用速率限制（預設 `60/minute`）。超過限制會回傳 `429 Too Many Requests`。透過 `RATE_LIMIT` 環境變數調整。

### Prometheus Metrics

`ENABLE_METRICS=true`（預設）時提供 `/metrics` 端點，輸出請求數、延遲分布與狀態碼統計，可接 Prometheus / Grafana。

```bash
curl http://localhost:8000/metrics
```

### Graceful Shutdown

關機時會等待最多 `SHUTDOWN_TIMEOUT` 秒（預設 30），讓執行中的任務完成後才停止 worker。

---

## 專案架構

### 執行流程

```text
客戶端請求 → FastAPI → JobManager → LabelPrintService → GlabelsEngine → PDF 輸出
                          ↓              ↓                  ↓
                      佇列管理        JSON→CSV          CLI 包裝器
                      Worker Pool     批次分割          subprocess
                                      PDF 合併
```

### 專案結構

```text
app/
├── api/
│   └── print_jobs.py      # API 路由與端點
├── core/
│   ├── limiter.py         # 速率限制器實例（SlowAPI）
│   ├── logger.py          # 日誌設定
│   └── version.py         # 版本資訊
├── parsers/
│   ├── base_parser.py     # 解析器基底類別
│   └── csv_parser.py      # CSV 格式解析器
├── services/
│   ├── job_manager.py     # 任務佇列與 worker 管理
│   ├── label_print.py     # JSON→CSV、批次分割、PDF 合併
│   └── template_service.py # 模板探索與解析
├── utils/
│   ├── cpu_detect.py      # 容器感知 CPU 偵測（cgroup）
│   └── glabels_engine.py  # glabels-3-batch CLI 包裝器
├── config.py              # 環境設定（pydantic-settings）
├── schema.py              # Pydantic 資料模型
└── main.py                # FastAPI 應用程式入口
```

### 主要元件說明

- **JobManager**：管理任務佇列、worker pool、任務狀態追蹤和清理
- **LabelPrintService**：處理 JSON 轉 CSV、批次分割、PDF 合併邏輯
- **GlabelsEngine**：非同步包裝 `glabels-3-batch` CLI，處理逾時與錯誤
- **TemplateService**：自動探索 `templates/` 目錄並解析 `.glabels` 檔案結構

---

## 模板與資料格式

### 模板檔案

- 將 `.glabels` 模板檔案放置於 `templates/` 目錄
- 目前僅支援 CSV/Comma 類型的模板 merge 設定
- 系統自動探索並解析模板中的欄位定義
- 使用 `/labels/templates` API 查看可用模板清單（僅摘要資訊，不含欄位列表）
- 使用 `/labels/templates/{template_name}` 取得指定模板的完整欄位與詳細資訊

### 資料格式要求

- JSON 資料欄位名稱必須與模板變數完全對應（區分大小寫）
- `data` 陣列不得為空
- 單次請求最多 `MAX_LABELS_PER_JOB` 筆（預設 2000）
- 單筆資料最多 `MAX_FIELDS_PER_LABEL` 個欄位（預設 50）
- 單一欄位值長度最多 `MAX_FIELD_LENGTH` 字元（預設 2048）

### 檔案輸出

- 產生的 PDF 儲存至 `output/` 目錄
- 檔名格式：`{template_name}_{timestamp}.pdf`
- 暫存 CSV 檔案位於 `temp/`（`KEEP_CSV=true` 時保留）
- 任務完成後保留 `RETENTION_HOURS` 小時（預設 24）

---

## 開發與測試

### 執行測試

```bash
# 執行所有測試
pytest tests/ -v

# 生成覆蓋率報告
pytest tests/ --cov=app --cov-report=html

# 檢視覆蓋率
open htmlcov/index.html

# 執行特定測試
pytest tests/test_glabels_engine.py -v
```

### 本地開發

```bash
# 建立虛擬環境
python -m venv venv
source venv/bin/activate

# 安裝開發依賴
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 安裝 gLabels（Linux/WSL）
sudo apt-get install glabels glabels-data fonts-dejavu fonts-noto-cjk

# 執行服務（啟用熱重載）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 或按 F5 在 VS Code 中除錯（會讀取 .env）
```
