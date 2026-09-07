# -*- coding: utf-8 -*-
"""Hugging Face Space（Gradio SDK）的進入點。

這個專案本身沒有用 Gradio，介面是自己的 index.html 加 Python 內建的 http.server。
Space 的 Gradio SDK 只做兩件事：跑 app.py，然後把 7860 埠反向代理出去，
所以把自己的伺服器綁在 7860 上就能用，不需要包成 Gradio 元件
（包成 Gradio 反而會失去鋼琴捲軸、試聽合成器那些自己寫的東西）。

只有 ZeroGPU 硬體多一道手續，見 satisfy_zerogpu()。
用 Docker SDK 的話請改用 Dockerfile，那份最單純。
"""
import importlib.util
import os
import subprocess
import sys

# ZeroGPU 握手用的內部埠。只綁 127.0.0.1，不對外。
HANDSHAKE_PORT = int(os.environ.get('ZEROGPU_HANDSHAKE_PORT') or 7861)


def satisfy_zerogpu():
    """在 ZeroGPU 硬體上完成啟動握手。

    免費帳號的 Gradio Space 只能用 ZeroGPU（Docker SDK 要付費，cpu-basic 要 PRO），
    而 ZeroGPU 啟動不成功就整個 Space 掛掉，錯誤是：
        No @spaces.GPU function detected during startup

    這個錯誤的訊息會誤導人。實際機制在 spaces/zero/__init__.py：

        def startup():
            ...
            if len(decorator.decorated_cache) == 0:
                return
            client.startup_report()

        gradio.one_launch(startup)

    而 one_launch 是把 gr.Blocks.launch 換掉，等你呼叫 launch() 時才執行 startup()。
    也就是說，光有 @spaces.GPU 函式沒有用——只要程式從頭到尾沒有呼叫過
    demo.launch()，那份 startup_report 就永遠不會送出，監督程序等不到就判定失敗。

    所以這裡開一個最小的 Gradio app 綁在 127.0.0.1 的內部埠上，純粹為了觸發那一次
    握手。它不對外、沒有人會看到，被裝飾的函式也永遠不會被呼叫——這個專案完全跑
    CPU（Basic Pitch 走 ONNX）。對外的 7860 仍然是我們自己的伺服器。

    非 ZeroGPU 的環境（cpu-basic、Docker、本機）沒有 SPACES_ZERO_GPU 這個環境變數，
    整段直接跳過。
    """
    if not os.environ.get('SPACES_ZERO_GPU'):
        return

    try:
        # spaces 必須在任何會初始化 CUDA 的套件之前 import，否則它自己會拋錯。
        # 這也是 satisfy_zerogpu() 要排在 import server 之前的原因。
        import spaces
        import gradio as gr
    except ImportError as e:
        print('[app] ZeroGPU 環境但缺少套件（%s），跳過握手' % e, flush=True)
        return

    @spaces.GPU(duration=1)
    def _unused():
        # 只是為了讓 decorated_cache 不是空的。永遠不會被呼叫。
        return 'ok'

    with gr.Blocks() as demo:
        gr.Markdown('這個頁面只是 ZeroGPU 的啟動握手，實際介面在 Space 的網址上。')
        out = gr.Textbox(visible=False)
        gr.Button('noop', visible=False).click(_unused, outputs=out)

    try:
        demo.launch(
            server_name='127.0.0.1',
            server_port=HANDSHAKE_PORT,
            prevent_thread_lock=True,   # 立刻返回，不要卡住主流程
            quiet=True,
            show_api=False,
            share=False,
            inbrowser=False,
        )
        print('[app] ZeroGPU 握手完成（內部埠 %d）' % HANDSHAKE_PORT, flush=True)
    except Exception as e:
        # 握手失敗的話 Space 大概還是會被判定啟動失敗，但至少日誌看得到原因，
        # 不要在這裡把整個程式帶走。
        print('[app] ZeroGPU 握手失敗：%r' % (e,), flush=True)


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
    # 順序有意義：握手要在 import server（會連帶 import librosa、numpy）之前做完，
    # spaces 套件要求自己排在任何 CUDA 相關套件前面。
    satisfy_zerogpu()
    ensure_basic_pitch()

    # HF 的代理固定打 7860，而且一定要綁 0.0.0.0；綁 127.0.0.1 從外面連不進來。
    port = os.environ.get('PORT') or '7860'
    os.environ['PORT'] = port
    os.environ['HOST'] = '0.0.0.0'
    os.environ['NO_BROWSER'] = '1'

    import server
    print('[app] 啟動伺服器，綁 0.0.0.0:%s' % port, flush=True)
    server.main()


if __name__ == '__main__':
    main()
