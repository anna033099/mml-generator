# 給 Hugging Face Spaces（Docker SDK）用的映像檔。
# 本機使用完全不需要這個檔案，點兩下「啟動網頁.bat」就好。
#
# HF Spaces 的規矩：容器要監聽 7860，而且必須綁 0.0.0.0（綁 127.0.0.1 外面連不進來）。
# server.py 會讀 HOST / PORT 環境變數，所以不用改程式。
FROM python:3.11-slim

# ffmpeg：yt-dlp 轉音訊要用。裝系統的版本，shutil.which('ffmpeg') 就找得到，
# 不會再去複製 imageio-ffmpeg 那份（那份是為了 Windows 上檔名不合的問題才有的）。
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# HF Spaces 以 uid 1000 執行，家目錄要可寫，不然模型快取會失敗
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HOST=0.0.0.0 \
    PORT=7860 \
    NO_BROWSER=1 \
    PYTHONUNBUFFERED=1

WORKDIR $HOME/app

COPY --chown=user requirements-hf.txt .
# 兩段式安裝：basic-pitch 一定要 --no-deps，直接裝會把 TensorFlow 一起拉進來
# 並把 numpy 降到 1.x。這裡只用它內附的 ONNX 模型（228 KB），不需要 TF。
RUN pip install --no-cache-dir --user -r requirements-hf.txt \
    && pip install --no-cache-dir --user --no-deps basic-pitch pretty_midi mir_eval

COPY --chown=user mabi3.py server.py msg.py index.html about.html ./

EXPOSE 7860
CMD ["python", "server.py"]
