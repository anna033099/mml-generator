# -*- coding: utf-8 -*-
"""Hugging Face Space（Gradio SDK）的進入點。

這個專案本身沒有用 Gradio，介面是自己的 index.html 加 Python 內建的 http.server。
Space 的 Gradio SDK 其實只做兩件事：跑 app.py，然後把 7860 埠反向代理出去。
所以這裡只要把我們自己的伺服器綁在 7860 上就行，不需要包成 Gradio 元件
（包成 Gradio 反而會失去鋼琴捲軸、試聽合成器那些自己寫的東西）。

用 Docker SDK 的話請改用 Dockerfile，那份比較單純。
"""
import importlib.util
import os
import subprocess
import sys


# ZeroGPU 硬體開機時會掃描程式裡有沒有被 @spaces.GPU 裝飾的函式，掃不到就直接判定
# 啟動失敗（Runtime error: No @spaces.GPU function detected during startup），
# 跟程式寫得對不對無關。
#
# 這個專案從頭到尾跑 CPU：Basic Pitch 走的是 ONNX，沒有任何一段需要 GPU。
# 但 Space 建立後若沒有 PRO 就不能把硬體降回免費的 cpu-basic，所以留一個空的
# 函式給它掃，讓 ZeroGPU 上的 Space 也能正常啟動。這個函式永遠不會被呼叫。
#
# cpu-basic 的映像檔裡沒有 spaces 這個套件，import 會失敗，整段跳過就好。
try:
    import spaces

    @spaces.GPU
    def _zerogpu_probe():
        return None

    print('[app] 偵測到 ZeroGPU 環境，已註冊佔位函式（實際運算仍在 CPU）', flush=True)
except Exception:
    pass


def ensure_basic_pitch():
    """補裝 basic-pitch。

    為什麼不寫在 requirements.txt：它一定要用 --no-deps 裝。直接裝會把
    TensorFlow 一起拉進來、並且把 numpy 降到 1.x，librosa 那些就壞了。
    而 pip 的 requirements.txt 格式不支援 --no-deps 這個選項（只吃
    --index-url、--find-links 那類），所以只能在開機時自己跑一次 pip。

    裝的是三個純 Python 的小輪子，幾秒就好；ONNX 模型只有 228 KB，附在套件裡。
    """
    # 用 find_spec 而不是 import：實際 import basic_pitch 會執行它的
    # __init__.py，而那裡第一件事就是 import tensorflow。mabi3.py 是靠在
    # import 之前先塞 sys.modules['tensorflow'] = None 把 TF 擋掉、逼它走 ONNX 的；
    # 在這裡先 import 就繞過了那道防護，環境裡真的有 TF 時會直接炸掉。
    # find_spec 只找套件位置，不會執行任何模組程式碼。
    if all(importlib.util.find_spec(m) for m in ('basic_pitch', 'pretty_midi', 'mir_eval')):
        print('[app] basic-pitch 已存在，跳過安裝', flush=True)
        return True

    print('[app] 安裝 basic-pitch（--no-deps，避免拉進 TensorFlow）...', flush=True)
    cmd = [sys.executable, '-m', 'pip', 'install', '--no-cache-dir',
           '--no-deps', 'basic-pitch', 'pretty_midi', 'mir_eval']
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        # 不要讓整個 Space 掛掉。採譜引擎會在使用者實際按下轉換時才報錯，
        # 至少介面、MIDI 匯入、貼現成 MML 這些還能用。
        print('[app] 警告：basic-pitch 安裝失敗，採譜功能會不能用', flush=True)
        return False
    print('[app] basic-pitch 安裝完成', flush=True)
    return True


def main():
    ensure_basic_pitch()

    # HF 的代理固定打 7860，而且一定要綁 0.0.0.0；綁 127.0.0.1 從外面連不進來。
    # GRADIO_SERVER_PORT 是 Gradio SDK 會設的，拿它當第二順位比較保險。
    port = os.environ.get('PORT') or os.environ.get('GRADIO_SERVER_PORT') or '7860'
    os.environ['PORT'] = port
    os.environ['HOST'] = '0.0.0.0'
    os.environ['NO_BROWSER'] = '1'

    import server
    print('[app] 啟動伺服器，綁 0.0.0.0:%s' % port, flush=True)
    server.main()


if __name__ == '__main__':
    main()
