---
title: 三軌樂譜產生器
emoji: 🎼
colorFrom: indigo
colorTo: purple
sdk: gradio
app_file: app.py
pinned: false
license: mit
short_description: 把一首歌自動改編成倩女幽魂編曲介面的三軌 MML
---

# 三軌樂譜產生器

把一首歌自動改編成《倩女幽魂》編曲介面能用的三軌 MML。

丟 MP3、貼 YouTube 連結、給 MIDI，或貼別人寫好的 MML，程式會採譜、抓速度、
分成三條單音旋律線，再寫成遊戲吃得下的 MML，分別貼進 **音軌A / 音軌B / 音軌C**。

三軌是一起組成一首曲子、同時播放，不是「主旋律加伴奏」。每軌上限 3000 字。

## 雲端版和本機版的差別

- **YouTube 連結在雲端常常會失敗**，主機 IP 會被限流。本機版通常沒事。
- 這是免費 Space，CPU 執行，多人同時用會排隊。

要完整功能請跑本機版，原始碼和安裝說明在
<https://github.com/anna033099/mml-generator>。

## 隱私

上傳的音檔會存在這個 Space 的暫存空間裡，Space 重啟就清空。
不想讓檔案離開自己電腦的話，請用本機版。

## 授權

MIT。用到的專案與各自授權詳見 GitHub 上的 README。
