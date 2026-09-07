# 三軌樂譜產生器

把一首歌自動改編成《倩女幽魂》編曲介面能用的三軌 MML。

丟 MP3、貼 YouTube 連結、給 MIDI，或貼別人寫好的 MML，程式會採譜、抓速度、
分成三條單音旋律線，再寫成遊戲吃得下的 MML，分別貼進 **音軌A / 音軌B / 音軌C**。

三軌是一起組成一首曲子、同時播放，不是「主旋律加伴奏」。每軌上限 3000 字。

---

## 功能

- **採譜**：Spotify Basic Pitch（預設，什麼樂器都聽、CPU 上一首 5 分鐘的歌約 6 秒）
  或 ByteDance 的鋼琴專用模型
- **來源**：MP3 / WAV / FLAC / OGG / M4A、MIDI、現成 MML 文字、YouTube 連結
- **樂器**：鋼琴、瑤箏、箜篌、電吉他、貝斯、笛子、小提琴、架子鼓
- **試聽**：瀏覽器即時合成，每個樂器有各自的音色；可單軌靜音／獨奏
- **鋼琴捲軸**：看得到哪些音被留下來，點一下就從那裡開始播
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
用 Hugging Face Spaces（免費、可跑 Python）：

1. 到 <https://huggingface.co/new-space> 建一個 Space，**SDK 選 Docker**
2. 把這個 repo 的檔案推上去（Space 本身就是一個 git repo）：

```bash
git clone https://huggingface.co/spaces/<你的帳號>/<space 名稱> hf-space
cd hf-space
cp ../Dockerfile ../requirements-hf.txt ../mabi3.py ../server.py ../msg.py ../index.html ../about.html .
git add -A && git commit -m "deploy" && git push
```

`Dockerfile` 已經處理好 HF 的規矩（監聽 7860、綁 `0.0.0.0`、裝 ffmpeg、
用 `--no-deps` 裝 basic-pitch）。`server.py` 讀 `HOST` / `PORT` 環境變數，本機行為不變。

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
| [Spotify Basic Pitch](https://github.com/spotify/basic-pitch) | 預設採譜模型（內附 ONNX 版） | Apache-2.0 |
| [ByteDance piano_transcription](https://github.com/bytedance/piano_transcription) | 鋼琴專用採譜模型 | Apache-2.0 |
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
| `Dockerfile` | 部署到 Hugging Face Spaces 用 |

---

## 授權

本專案採用 [MIT License](LICENSE)，可自由使用、修改、再散布，附上授權條款即可。

上表列出的第三方專案各自有自己的授權，另外注意 FFmpeg 依編譯選項可能是 GPL；
如果你要把這個工具再包成產品散布，記得分別確認。
