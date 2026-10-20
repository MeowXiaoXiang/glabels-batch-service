# gLabels Batch Service

非同步標籤 PDF 服務，GTK 與 Qt 共用同一套 API、排程及合併流程。一次提交對應一個 job_id 與一份 final PDF；CSV、batch PDF 都是完成後清除的中間產物。

[English／完整設定說明](README.md)

參與開發與 commit 格式規範：[CONTRIBUTING.md](CONTRIBUTING.md)。

## 啟動

預設 Docker image 已包含 Python、GTK、中文字型與 Python 依賴，主機只需備妥 Docker 與 Compose：

```powershell
Copy-Item .env.example .env
# 將自己的模板放入 templates，使用含 header 的 named CSV。
docker compose up --build -d
curl.exe http://localhost:8000/ready
```

Compose 會持久掛載 state、output、templates 與 logs。state 保存 SQLite，output 保存 final，兩者都要保留。每個 store 只支援一個服務實例、一個 Uvicorn worker；第二個 owner 會被拒絕，不能直接加 workers 擴充。

不使用 Docker 時，請先準備 Python 3.14 以上、可運作的 gLabels batch executable、原生函式庫與字型，再使用 uv 0.12.10（需要安裝時可執行 `python -m pip install uv==0.12.10`）：

```powershell
uv sync --locked --no-dev
uv run --locked --no-dev python -m app.main
```

已驗證的 runtime 為 Python 3.14。uv 將依賴裝入專案自己的 `.venv`，不修改系統 Python 套件；使用 Docker 時不需要在主機另外裝 uv。

`HOST`、`PORT`、`RELOAD` 用於 `python -m app.main` 啟動方式。Docker 的啟動命令固定使用容器內的 8000 port；要換主機 port，請修改 Compose 的 port mapping。Docker 與 `python -m app.main` 都把 Uvicorn 並行上限設為128。

API 沒有內建身分驗證，請部署在可信任的網路，或由前方 gateway 控制存取。

## GTK／Qt 切換

**一個服務實例只使用一種 renderer**，在部署時統一選定。API 不提供逐請求選 GTK／Qt，同一個 job 也不混用兩套。

目前 Docker targets：

| 建置 target | 包含的 renderer | 預設執行 |
|---|---|---|
| `production`（預設，Compose 亦使用此版本） | GTK | API 服務 |
| `test` | GTK | pytest |
| `qt-test` | GTK 與 Qt | pytest |

`qt-test` 同時裝兩套是為了相容性測試。Qt 專用的正式 target 尚未提供；預設 GTK image 不會因改了環境變數就安裝 Qt，切換前須先部署對應 runtime。

設定 `GLABELS_EXECUTABLE` 為執行檔名稱或路徑，重啟即可套用。預設 `glabels-3-batch`，Qt 可用 `glabels-batch-qt` 或相容 wrapper。服務用獨立 argv 傳遞 `-o`、`-i`、`--copies=1` 與 template，不執行 shell command 字串。

請先準備對應的 renderer、runtime、字型與平台環境。更換路徑不會安裝 Qt；無顯示器的 Qt 部署可提供適用的 `QT_QPA_PLATFORM=offscreen` 或 wrapper。wrapper 要正確傳參數、退出碼與信號並管理子程序。預設 production image 保留 GTK，`qt-test` target 另行建置固定 Qt 上游版本供驗證。

模板內容完全由 renderer 理解，服務不解析／轉換 XML、不推測欄位、不提供 sidecar metadata。模板提供者負責選用相容格式及正確的 CSV 欄位設定。

份數與排列由服務統一處理，renderer 固定收到 copies=1；用法見下方的「copies 與 copy_order 怎麼用」。

有效標籤數超過 `MAX_LABELS_PER_BATCH`、需要拆批時，請求必須提供該模板的 `labels_per_page`。中間批次會在上限內向下對齊完整頁，最後一批才可有空格。缺少宣告、一頁超過批次上限、批數或宣告頁數超限，會在建立 job 前回 422；單次 render 可省略宣告。隔離的 merge worker 會檢查每批 PDF 的實際頁數，不符就失敗、不發布 final。

模板提供者須確認每頁容量、從第一格開始、連續填格且不使用原生分組。服務不解析模板，也無法只靠 PDF 頁數證明每一格的位置。業務流水號或需要跨批一致的 copy／page 值應放進輸入欄位；原生 copy 變數現在只看到 copies=1，原生頁碼／流水變數仍會每批重設。依賴這些功能的模板需要調整並驗收，不能宣稱任意模板皆等同一次完整 render。

## 提交與下載

以下範例假設你已部署名為 `demo.glabels`、使用 `ITEM` 與 `CODE` 欄位的相容模板。正式 image 不會安裝 demo 模板。[test_data](test_data/README.md) 保留了可供手動測試的 GTK 範例；自動化測試使用另一組 GTK／Qt fixture。

向 `POST /labels/print` 提交：

```json
{
  "template_name": "demo.glabels",
  "data": [{"ITEM": "A001", "CODE": "123"}],
  "copies": 1
}
```

接受後回202與 job_id。透過 `/labels/jobs/{job_id}` 查狀態，或 `/labels/jobs/{job_id}/stream` 訂閱 SSE；done 後使用 response 的 download_url。斷線不取消工作。

### copies 與 copy_order 怎麼用

`copies` 決定每筆資料產生幾張標籤；`copy_order` 決定這些標籤的排列。
它是每次 `POST /labels/print` 的 JSON 欄位，不是環境變數，也不需要另加 Qt 參數。
服務依指定順序逐筆寫入各批 CSV，不會在記憶體另外建立包含全部 copies 的展開清單。

例如，假設你已部署的 `demo.glabels` 使用 `ITEM` 欄位，而且每頁有4個標籤位置：

```json
{
  "template_name": "demo.glabels",
  "data": [{"ITEM": "A"}, {"ITEM": "B"}, {"ITEM": "C"}],
  "copies": 2,
  "copy_order": "sets",
  "labels_per_page": 4
}
```

| copy_order | 意義 | 標籤順序 | 此範例的分頁（`｜` 表示換頁） |
|---|---|---|---|
| `sets`（預設） | 整份資料依序重複 | `ABCABC` | `ABCA｜BC` |
| `per_record` | 每筆資料連續重複 | `AABBCC` | `AABB｜CC` |

要改成逐筆重複，只需把同一請求的 `copy_order` 改成 `"per_record"`。
省略 `copy_order` 就用 `sets`；省略 `copies` 就印一份，此時兩種排列結果相同。
`sets` 不會強制每套從新頁開始，也不會產生兩個 PDF；這個範例兩種模式都產生6張標籤、同一份兩頁 PDF。

`labels_per_page` 請填實際模板容量，不能直接照抄範例的4。它用來對齊服務批界，沒有控制或修改模板的格數；需要拆批時必填。

狀態：`pending → rendering → merging → done`，失敗為 failed。單 batch 可略過 merging，但一樣由隔離 worker 驗證 PDF。進度表示完成 render 的批數，還不代表 final 已能下載。batch 只有內部 index，不另外提供母／子 job ID。

SSE 的 `status` 事件包含 job JSON；狀態未變時送出 keepalive 註解。工作 done／failed、服務停止接單或用戶端斷線時結束串流。開始前找不到工作會回 HTTP 404；串流開始後才到期，則送出內容為 `{"code":"not_found"}` 的 `error` 事件後結束。

請求欄位：`copies` 預設 1、`copy_order` 為 `sets`／`per_record`、`labels_per_page` 為正整數或 null。狀態與 SSE 會保存排列／分頁宣告供重啟後查詢。SQLite schema v1 已包含排列與分頁欄位；遇到不支援的結構版本會在啟動時拒絕開啟。

資料只接受 scalar；CSV 依全 job 欄位首次出現順序產生一致 header，UTF-8 編碼、標準 quoting，null／缺值為空字串，boolean 為 true／false。巢狀物件、NUL、非有限數字會被拒絕。

## 保存與重啟

SQLite 只保存必要 metadata，PDF 放在 `output/<job_id>.pdf`。完成結果預設保留24小時，重啟後仍可用原 ID 查詢與下載；重啟、重新下載及修改 retention 都不延長既有 expiry。

正常處理結束後會移除 CSV、batch PDF 與暫存檔。強制停止留下的檔案，若仍存在，會在工作到期時清除，不會用來自動續跑。

已發布 final 但來不及記 done 的工作，啟動時會依 publication intent 驗證並修復。其他未完成工作標記 failed/interrupted，不自動續跑、不保存完整 payload，也不保證重送去重。

到期立即停止新存取並回404，背景清理可稍晚完成。既有下載會受保護，先刪 artifact 再刪 DB row；刪除失敗保留到期紀錄供重試。未過期的 done 若檔案意外缺失回410，尚未完成回409。failed 紀錄也會到期。舊版未入索引的 PDF 不會自動匯入或清除。

### 查看與備份 SQLite

平常查詢請用狀態或工作清單 API。Docker 執行中若需要 SQL，請在服務容器內使用短時間、唯讀的連線，查完就關閉；避免用 Windows 端 SQLite 工具直接開啟 Linux 容器正在使用的掛載資料庫。儲存位置必須支援 SQLite 的鎖定與共享記憶體機制，WAL 不支援網路檔案系統，詳見 [SQLite WAL 說明](https://sqlite.org/wal.html)。

要一起備份 metadata 與 PDF，請先停止服務、確認程序已退出，再同時複製 `state/` 與 `output/`（若自訂路徑，請複製對應目錄），完成後再啟動。`state/` 要整個複製，包含可能殘留的 WAL 檔案，不要只拿 `jobs.sqlite3`。SQLite 的 [backup API](https://sqlite.org/backup.html) 可在執行中取得一致的資料庫副本，但不會一起快照 PDF 目錄。

## 容量與關閉

CPU budget 在啟動時計算：取偵測到的最小 CPU 容量向下取整，減去 `API_CPU_RESERVE`（預設1），至少保留1個 work token，因此0.5 CPU 也能執行。render 成本為1、merge 預設為2；merge 成本最多等於總 budget。工作動態派發，沒有即時 CPU feedback；`WORK_TOKENS=0` 自動計算，正值可進一步降低總容量。

render／merge 共用 budget，等待 merge 時保留收尾容量；render 依 job 輪替，低容量下也讓新 render 在連續 merges 間前進。一個常駐 spawn worker 處理 merge／validation，只有確認真正退出後才能釋放 lease 或清理使用中的檔案。

queue、inflight、request、records×copies、batch、PDF pages／bytes、workspace 與磁碟餘裕都有上限。workspace／磁碟會在操作前後及 render 期間定期檢查；硬性 OS 資源隔離仍由容器／supervisor 提供。請用會管理整棵程序樹的 supervisor；提供的 Docker 部署是此運行模式。

SIGTERM 先停止接單並等待已接受的工作完成，超過期限再停止及回收子程序。`/health` 是存活檢查，`/ready` 檢查協調器是否運行且健康，不檢查佇列或磁碟餘裕；即使 ready，提交仍可能因容量不足回503。過大 body 回413。一般 process／container restart 已納入保存契約，突然斷電的 volume 耐久度需另外驗證。

## 驗證與升級

依賴與工具設定集中在 `pyproject.toml`：正式依賴放 `project.dependencies`，開發工具放 `dependency-groups.dev`。`uv.lock` 由工具產生並一起進 Git，鎖住 Windows／Linux 所需的間接版本與套件雜湊，不手動維護另一份 txt。

開發環境執行 `uv sync --locked`，測試用 `uv run --locked python -m pytest`。CI／Docker 同樣使用 `--locked`；宣告與 lock 不一致就失敗，正式部署加上 `--no-dev`。Python／uv 建置映像固定 digest，正式容器直接啟動 Uvicorn，uv 僅在安裝時掛載。gLabels、Qt／GTK、字型與 OS 套件由部署環境另外管理，預設 Docker image 安裝 GTK 所需套件；依賴更新方式見 [CONTRIBUTING.md](CONTRIBUTING.md)。

使用 [tests/README.md](tests/README.md) 的品質檢查與 GTK／Qt container tests。正式 image 不放 research、tests、Qt 編譯工具或 qpdf CLI；服務程式不解析模板內容。

v3 直接更新 API 與設定：移除 running、模板解析欄位、MAX_PARALLEL、KEEP_CSV，請對照新的 `.env.example`。不維護舊版相容層。

## 日誌與 API 文件

`LOG_LEVEL` 是應用程式日誌的最低門檻。Console 直接使用此等級；`system.log` 取它與 INFO 較嚴格者，`error.log` 取它與 ERROR 較嚴格者。因此 DEBUG 只進 console；設為 ERROR 後，應用程式的所有日誌輸出都排除 INFO。`LOG_FORMAT=text`／`json` 同時套用至 console 與檔案；目錄或檔案建立失敗時，console 仍維持指定等級與格式。每個檔案 sink 在 5 MB 輪替，保留 10 份輪替檔案。Uvicorn 自己的伺服器日誌使用另一套 logging 設定。

`/docs` 提供請求範例、欄位語意、PDF／SSE 格式及錯誤回應。部署限制使用目前 app 的設定，在接受任務前檢查；型別與基本資料有效性由模型另外驗證。提交限流依用戶端位址及服務 instance 分別計數，不跨部署共用。
