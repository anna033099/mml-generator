# 三軌樂譜產生器

把一首歌自動改編成《倩女幽魂》編曲介面能用的三軌 MML。

**線上直接用：<https://chenpinzhen-mml-generator.hf.space>**
（免費 Space、CPU 執行，多人同時用會排隊；要完整功能請跑本機版）

丟 MP3、貼 YouTube 連結、給 MIDI，或貼別人寫好的 MML，程式會採譜、抓速度、
分成三條單音旋律線，再寫成遊戲吃得下的 MML，分別貼進 **音軌A / 音軌B / 音軌C**。

三軌是一起組成一首曲子、同時播放，不是「主旋律加伴奏」。每軌上限 3000 字。

---

## 功能

- **採譜**：Spotify Basic Pitch（什麼樂器都聽，CPU 上一首 5 分鐘的歌約 6 秒）
- **來源**：MP3 / WAV / FLAC / OGG / M4A、MIDI、現成 MML 文字、YouTube 連結
- **樂器**：鋼琴、瑤箏、箜篌、電吉他、貝斯、笛子、小提琴、架子鼓
- **試聽**：瀏覽器即時合成，每個樂器有各自的音色；可單軌靜音／獨奏
- **鋼琴捲軸**：看得到哪些音被留下來，點一下就從那裡開始播
- **副歌讓路**：主旋律衝高音時讓 B／C 退開、補低八度支撐、主旋律推到最大音量（不改主旋律的音）
- **字數上限就是豐富度旋鈕**：調大自動選更密的版本，調小自動變簡單，每軌各自挑

---

## 安裝與使用（Windows）

1. 裝 Python 3.11（安裝時勾選 **Add Python to PATH**）
2. 點兩下 **`安裝.bat`**
3. 點兩下 **`啟動網頁.bat`**，瀏覽器會打開 <http://127.0.0.1:8765>

> **不要只跑 `pip install -r requirements.txt`。**
> `basic-pitch` 必須用 `--no-deps` 安裝，直接裝會把 TensorFlow 一起拉進來、
> 並把 numpy 降到 1.x，環境裡其他套件會壞掉。`安裝.bat` 已經處理好順序。

手動安裝的話：

```bash
pip install -r requirements.txt
pip install --no-deps basic-pitch pretty_midi mir_eval
python server.py
```

不開網頁也可以直接用指令：

```bash
python mabi3.py 歌.mp3 --instrument piano --limit 3000
```

詳細用法和調整項目看 [使用說明.md](使用說明.md)。

---

## 這一套 MML 的幾個坑

做這個工具時實際踩到、也寫進程式裡的：

- **沒有 `l`（預設音長）指令。** 寫了 `l16` 再用裸音符，遊戲會把裸音符當成四分音符：
  音高全對、節奏全平，整首變成一樣長的「咚咚咚」，各軌長度不一致還會互相對不上。
  所以每個音、每個休止符都自己標長度。
- **速度 `t` 要寫進三軌各自的開頭。** 只寫在第一軌，另外兩軌會用預設速度跑掉。
- **樂譜欄不收** 中文、中文標點和 `￥ $ @ * \ [ ] | %`。所以不要貼整段 `MML@…,…;`
  （開頭的 `@` 和逗號都不合規），要用單軌的「複製」。
- **鍵盤範圍 C1～C8**，超出的音會被摺回八度。

---

## 部署到 Hugging Face Spaces

GitHub Pages 只能放靜態檔案，跑不了這個工具的 Python 後端。要讓別人用網址直接使用，
用 Hugging Face Spaces（免費、可跑 Python）。

先產生上傳包：

```bash
python make_hf_space.py
```

會在 `hf-space/` 生出 10 個檔案（約 120 KB）。到 <https://huggingface.co/new-space>
建一個 Space，再到 **Files → Add file → Upload files**，把 `hf-space/` 裡的檔案
全部拖進去就好。之後改了程式，重跑一次這支再上傳一次即可。

**免費帳號只能選 Gradio + ZeroGPU。** Docker SDK 標了 `Paid`；Gradio SDK 底下的
`CPU Basic` 是灰的，提示寫「On the free tier, Gradio Spaces run on ZeroGPU」。
而且 Space 一旦建立，沒有 PRO 就不能把硬體改回 cpu-basic，重建也一樣選不到。

ZeroGPU 開機時會掃描程式裡有沒有被 `@spaces.GPU` 裝飾的函式，掃不到就直接
`Runtime error: No @spaces.GPU function detected during startup`。所以 `app.py`
留了一個永遠不會被呼叫的空函式給它掃——這個專案完全跑 CPU（Basic Pitch 走 ONNX），
一段都不需要 GPU。cpu-basic 的映像檔沒有 `spaces` 套件，那段 import 會失敗、自動跳過，
所以同一份 `app.py` 兩種硬體通用。

上傳包兩種 SDK 都附了，之後有 PRO 或換平台可以直接切：

- **Gradio**：執行 `app.py`。這個專案其實沒有用 Gradio，Space 的 Gradio SDK
  做的事只是「跑 app.py，然後把 7860 埠反向代理出去」，所以 `app.py` 直接把
  自己的 http.server 綁在 7860 上，介面維持原本的 `index.html`。
  要裝的 apt 套件（ffmpeg）寫在 `packages.txt`。
- **Docker**：執行 `Dockerfile`，流程比較單純。改用它的話，把 `README.md` 開頭
  frontmatter 裡的 `sdk: gradio` / `app_file: app.py` 換成
  `sdk: docker` / `app_port: 7860`。

兩種版本都要處理同一件事：`basic-pitch` 一定要用 `--no-deps` 裝，
而 pip 的 requirements.txt 格式不支援這個選項。Docker 版寫在 `Dockerfile` 裡，
Gradio 版則是在 `app.py` 開機時補跑一次 pip。

**上線前先想清楚兩件事：**

- 別人上傳的音檔會進到你的 Space，不再像本機版只留在自己電腦。
- YouTube 連結在雲端主機常常會被擋（IP 被限流），本機通常沒事。

---

## 限制

- 三條線都是**單音**。同一時刻超過三個音，多的一定會被丟掉，這是三軌的硬限制。
- 網頁試聽只是簡單合成，跟遊戲音色不一樣，**以遊戲裡聽到的為準**。
- 採譜是機器聽的。人聲、鼓、破音多的原曲會亂，該樂器的獨奏 Cover 最準。
- 架子鼓是用起音偵測分頻帶抓的（不是 AI 模型），複雜的鼓組會誤判。

---

## 用到的專案

| 專案 | 用途 | 授權 |
|---|---|---|
| [Spotify Basic Pitch](https://github.com/spotify/basic-pitch) | 採譜模型（內附 ONNX 版） | Apache-2.0 |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | YouTube 抓音訊 | Unlicense |
| [FFmpeg](https://ffmpeg.org/) | 音訊轉檔 | LGPL / GPL |
| [librosa](https://librosa.org/) | 音訊分析、鼓點偵測 | ISC |
| [mido](https://mido.readthedocs.io/) | 讀寫 MIDI | MIT |
| [soundfile](https://python-soundfile.readthedocs.io/) | 讀 MP3 / WAV | BSD |
| [NumPy](https://numpy.org/) · [ONNX Runtime](https://onnxruntime.ai/) | 數值運算、模型推論 | BSD / MIT |

網頁後端只用 Python 內建的 `http.server`，沒有其他框架；
試聽是瀏覽器的 Web Audio API 即時合成，沒有取樣音源。

---

## 檔案

| 檔案 | 做什麼 |
|---|---|
| `mabi3.py` | 轉換核心：採譜、抓速度、分三軌、配音量、寫 MML。也可以單獨當指令用 |
| `server.py` | 網頁後端，Python 內建 http.server |
| `index.html` | 介面：鋼琴捲軸、試聽合成器、調整面板 |
| `about.html` | 關於本站 |
| `msg.py` | 印中文提示給 .bat 用（.bat 本身必須是純 ASCII，見檔案內註解） |
| `安裝.bat` / `啟動網頁.bat` / `轉換.bat` | Windows 一鍵操作 |
| `Dockerfile` | 部署到 Hugging Face Spaces（Docker SDK）用 |
| `deploy/` | 只有雲端要的檔案：`app.py`（Gradio SDK 進入點）、`packages.txt`、Space 首頁 |
| `make_hf_space.py` | 把上面這些打包成 `hf-space/`，直接上傳到 Space |

---

## 授權

本專案採用 [MIT License](LICENSE)，可自由使用、修改、再散布，附上授權條款即可。

上表列出的第三方專案各自有自己的授權，另外注意 FFmpeg 依編譯選項可能是 GPL；
如果你要把這個工具再包成產品散布，記得分別確認。
