# gLabels Batch Service

非同步標籤 PDF 服務，GTK 與 Qt 共用同一套 API、排程及合併流程。一次提交對應一個 job_id 與一份 final PDF；CSV、batch PDF 都是完成後清除的中間產物。

[English／完整設定說明](README.md)

## 啟動

需要 Python 3.14 以上與可運作的 gLabels batch executable。預設 Docker image 已包含 GTK、中文字型與 Python 依賴：

```powershell
Copy-Item .env.example .env
# 將自己的模板放入 templates，使用含 header 的 named CSV。
docker compose up --build -d
curl.exe http://localhost:8000/ready
```

Compose 會持久掛載 state、output、templates 與 logs。state 保存 SQLite，output 保存 final，兩者都要保留。每個 store 只支援一個服務實例、一個 Uvicorn worker；第二個 owner 會被拒絕，不能直接加 workers 擴充。

## GTK／Qt 切換

設定 `GLABELS_EXECUTABLE` 為執行檔名稱或路徑，重啟即可套用。預設 `glabels-3-batch`，Qt 可用 `glabels-batch-qt` 或相容 wrapper。服務用獨立 argv 傳遞 `-o`、`-i`、`--copies` 與 template，不執行 shell command 字串。

請先準備對應的 renderer、runtime、字型與平台環境。更換路徑不會安裝 Qt；無顯示器的 Qt 部署可提供適用的 `QT_QPA_PLATFORM=offscreen` 或 wrapper。wrapper 要正確傳參數、退出碼與信號並管理子程序。預設 production image 保留 GTK，`qt-test` target 另行建置固定 Qt 上游版本供驗證。

模板內容完全由 renderer 理解，服務不解析／轉換 XML、不推測欄位、不提供 sidecar metadata。模板提供者負責選用相容格式及正確的 CSV 欄位設定。

`copies` 採各 renderer **每個 batch 的原生語意**；GTK／Qt 順序可能不同。每批會從新頁開始，PDF merge 只串接完整頁，不回填前批尾頁的空標籤。跨批連續編號應由輸入欄位提供。

## 提交與下載

向 `POST /labels/print` 提交：

```json
{
  "template_name": "demo.glabels",
  "data": [{"ITEM": "A001", "CODE": "123"}],
  "copies": 1
}
```

接受後回202與 job_id。透過 `/labels/jobs/{job_id}` 查狀態，或 `/labels/jobs/{job_id}/stream` 訂閱 SSE；done 後使用 response 的 download_url。斷線不取消工作。

狀態：`pending → rendering → merging → done`，失敗為 failed。單 batch 可略過 merging，但一樣由隔離 worker 驗證 PDF。進度表示完成 render 的批數，還不代表 final 已能下載。batch 只有內部 index，不另外提供母／子 job ID。

資料只接受 scalar；CSV 依全 job 欄位首次出現順序產生一致 header，UTF-8 編碼、標準 quoting，null／缺值為空字串，boolean 為 true／false。巢狀物件、NUL、非有限數字會被拒絕。

## 保存與重啟

SQLite 只保存必要 metadata，PDF 放在 `output/<job_id>.pdf`。完成結果預設保留24小時，重啟後仍可用原 ID 查詢與下載；重啟、重新下載及修改 retention 都不延長既有 expiry。

已發布 final 但來不及記 done 的工作，啟動時會依 publication intent 驗證並修復。其他未完成工作標記 failed/interrupted，不自動續跑、不保存完整 payload，也不保證重送去重。

到期立即停止新存取並回404，背景清理可稍晚完成。既有下載會受保護，先刪 artifact 再刪 DB row；刪除失敗保留到期紀錄供重試。未過期的 done 若檔案意外缺失回410，尚未完成回409。failed 紀錄也會到期。舊版未入索引的 PDF 不會自動匯入或清除。

## 容量與關閉

CPU budget 依 quota、affinity 與 process CPU count 決定，預設保留1份餘裕。render=1、merge=2 作為靜態 admission weight，低 CPU 會 clamp；工作動態派發，沒有即時 CPU feedback。`WORK_TOKENS` 可進一步降低總容量。

render／merge 共用 budget，等待 merge 時保留收尾容量；render 依 job 輪替，低容量下也讓新 render 在連續 merges 間前進。一個常駐 spawn worker 處理 merge／validation，只有確認真正退出後才能釋放 lease 或清理使用中的檔案。

queue、inflight、request、records×copies、batch、PDF pages／bytes、workspace 與磁碟餘裕都有上限。workspace／磁碟會在操作前後及 render 期間定期檢查；硬性 OS 資源隔離仍由容器／supervisor 提供。請用會管理整棵程序樹的 supervisor；提供的 Docker 部署是此運行模式。

SIGTERM 先停止接單並 drain，超過期限再停止及回收子程序。`/health` 是存活檢查，`/ready` 是可接工作檢查；容量滿回503、過大 body 回413。一般 process／container restart 已納入保存契約，突然斷電的 volume 耐久度需另外驗證。

## 驗證與升級

使用 [tests/README.md](tests/README.md) 的品質檢查與 GTK／Qt container tests。正式 image 不放 research、tests、Qt 編譯工具、qpdf CLI 或模板 parser。

v3 直接更新 API 與設定：移除 running、模板解析欄位、MAX_PARALLEL、KEEP_CSV，請對照新的 `.env.example`。不維護舊版相容層。
