# 00981A 每日持股 Podcast 自動化

每個交易日 17:30 自動抓取「**統一台股增長主動式 ETF (00981A)**」持股變化，用 Claude Sonnet 4.6 撰寫講稿，Edge TTS 用台灣腔朗讀，最後透過 GitHub Pages RSS feed 自動同步至 **Apple Podcasts** 與 **Spotify**。

**月運行成本：~NT$60–120**（僅 Claude API 費用）

---

## 系統架構

```
GitHub Actions (cron 17:30) → 抓取 00981A 持股 → 與昨日比對
                                    ↓
                       Claude Sonnet 4.6 生成講稿
                                    ↓
                       Edge TTS (zh-TW) 朗讀 + 片頭片尾
                                    ↓
              上傳 Cloudflare R2 → 更新 RSS (GitHub Pages)
                                    ↓
              Apple Podcasts / Spotify 自動 fetch（一次性設定）
```

---

## 快速開始

### 1. 本機環境準備

```bash
# Python 3.12+
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

# 必須安裝 ffmpeg（音訊處理）
# Windows: choco install ffmpeg  或從 https://ffmpeg.org 下載
```

### 2. 環境變數

複製 `.env.example` 為 `.env` 並填入：
- `ANTHROPIC_API_KEY`：到 [console.anthropic.com](https://console.anthropic.com) 申請
- `R2_*`：在 [Cloudflare R2](https://dash.cloudflare.com/?to=/:account/r2) 建立 bucket 與 API token

### 3. 準備素材

放入 `assets/` 資料夾：
- `intro.mp3`：片頭音樂 3–5 秒（[FreePD.com](https://freepd.com) / [Pixabay Music](https://pixabay.com/music/) CC0 來源）
- `outro.mp3`：片尾音樂 3–5 秒
- `cover.png`：節目封面 1400×1400 PNG（Apple Podcasts 規範）

### 4. 本機 dry-run 驗證

```bash
python -m src.main --dry-run
# 產出在 build/episodes/<date>/final.mp3
# 用本機播放器確認音質與內容
```

### 5. 部署到 GitHub Actions

1. 在 GitHub 建立 repository（私有/公開皆可）
2. 推送本地 code
3. **Settings → Secrets and variables → Actions** 設定：
   - **Secrets**：`ANTHROPIC_API_KEY`、`R2_ACCESS_KEY`、`R2_SECRET_KEY`、`R2_BUCKET`、`R2_ENDPOINT`、`R2_PUBLIC_URL`、`DISCORD_WEBHOOK`（選用）
   - **Variables**：`PODCAST_TITLE`、`PODCAST_AUTHOR`、`PODCAST_EMAIL`、`PODCAST_DESCRIPTION`、`PODCAST_HOMEPAGE`、`PODCAST_COVER_URL`、`PODCAST_CATEGORY`、`PODCAST_SUBCATEGORY`、`TTS_VOICE`
4. **Settings → Pages**：Source 選 `GitHub Actions`
5. 推送一次更新觸發 `deploy-pages.yml`，確認 `https://USERNAME.github.io/REPO_NAME/feed.xml` 可訪問
6. 手動觸發測試：**Actions → Daily 00981A Podcast → Run workflow**

### 6. 上架雙平台（一次性）

#### Apple Podcasts
1. 至 [Apple Podcasts Connect](https://podcastsconnect.apple.com/)（需 Apple ID）
2. **+ New Show → Add a show with an RSS feed**
3. 貼上 `https://USERNAME.github.io/REPO_NAME/feed.xml`
4. 等待 1–7 天審核

#### Spotify for Podcasters
1. 至 [Spotify for Podcasters](https://podcasters.spotify.com/)
2. **Add existing podcast → 貼 RSS URL**
3. Email 驗證後即上架（通常數小時內）

之後每日新節目透過 RSS 自動同步，**無須再人工操作**。

---

## 專案結構

```
src/
├── data/             # 持股抓取、比對、催化劑
├── script/           # Claude 講稿 + prompt 模板
├── audio/            # Edge TTS + 後製
├── publish/          # R2 上傳 + RSS feed
├── utils/            # config、logger、notify
└── main.py           # 主流程入口

.github/workflows/
├── daily-podcast.yml # 每日 cron (台北 17:30)
└── deploy-pages.yml  # docs/ → GitHub Pages

docs/                 # GitHub Pages 根（feed.xml + index.html）
data/holdings/        # 每日持股快照（JSON，git-tracked）
assets/               # 片頭/片尾/封面
build/                # 暫存產出（.gitignore）
```

---

## 常用指令

| 指令 | 用途 |
|------|------|
| `python -m src.main --dry-run` | 完整本機測試（不上傳） |
| `python -m src.main --date 2026-04-25 --dry-run` | 指定日期測試 |
| `python -m src.audio.tts --text "今天台積電" --out test.mp3` | TTS 預覽 |
| `python -m src.data.fetch_holdings` | 僅抓取今日持股 |
| `pytest tests/ -v` | 執行單元測試 |

---

## 切換語音

`.env` 修改 `TTS_VOICE`：
- `zh-TW-HsiaoChenNeural`（女，預設、最自然）
- `zh-TW-YunJheNeural`（男）
- `zh-TW-HsiaoYuNeural`（女，較年輕）

---

## 風險與緩解

| 風險 | 緩解 |
|------|------|
| 統一投信網站改版 | 三來源 fallback：ezmoney → cmoney → pocket |
| Edge TTS 偶發失敗 | tenacity 指數退避重試 3 次 |
| RSS 損壞 | 每次提交前 feedparser 自我驗證 |
| 假日誤觸發 | cron 限週一~五；`_is_trading_day()` 雙重保險 |
| 合規 | prompt 強制免責聲明，禁用「推薦」「目標價」 |

---

## 延伸方向

- 加入「**法說會行事曆**」資料來源：豐富催化劑說明
- 動態封面：在每集封面上印當日日期
- 多 ETF 支援：把 `00981A` 改參數化即可支援其他主動式 ETF
- 更換 TTS：`src/audio/tts.py` 介面已抽象，可改 ElevenLabs / F5-TTS
