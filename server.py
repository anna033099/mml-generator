#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — mabi3 的網頁介面（只在你自己的電腦上跑，不用架伺服器）

    python server.py          # 會自動打開瀏覽器，網址 http://127.0.0.1:8765
    python server.py 9000     # 換一個埠號

不需要額外安裝任何網頁套件；採譜功能一樣靠 requirements.txt 裡的東西。
"""
import os
import sys
import json
import time
import uuid
import threading
import webbrowser
import traceback
from urllib.parse import urlparse, parse_qs, unquote
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mabi3  # noqa: E402

JOBS_DIR = os.path.join(HERE, 'jobs')
JOBS = {}

# Python 是在行程啟動時就把 mabi3.py 讀進記憶體的，之後改檔案不會影響已經在跑的
# 伺服器。網頁的 index.html 卻是每次請求都從硬碟讀——結果就是「新的選項出現了，
# 但按下去完全沒作用」，非常難察覺。這裡記下啟動當下的檔案時間，之後如果檔案
# 變新了就在每個 API 回應裡加上 stale 旗標，網頁會跳出「請重新啟動」的提示。
_WATCH = [os.path.join(HERE, f) for f in ('mabi3.py', 'server.py', 'msg.py')]
_MTIME = {}
for _f in _WATCH:
    try:
        _MTIME[_f] = os.path.getmtime(_f)
    except OSError:
        pass


def sources_changed():
    for f, t in _MTIME.items():
        try:
            if os.path.getmtime(f) != t:
                return True
        except OSError:
            pass
    return False
LOCK = threading.Lock()
ALLOWED = mabi3.AUDIO_EXT + ('.mid', '.midi', '.mml')


def params_from_json(d):
    d = d or {}
    bpm = d.get('bpm')
    try:
        bpm = float(bpm) if bpm not in (None, '', 'auto') else None
    except (TypeError, ValueError):
        bpm = None
    return mabi3.Params(
        bpm=bpm,
        octave_shift=int(d.get('octave_shift', 0) or 0),
        inner=d.get('inner') if d.get('inner') in ('near', 'high', 'long') else 'near',
        min_vel=int(d.get('min_vel', 20) or 0),
        grid=int(d.get('grid', 4) or 4),
        limit=int(d.get('limit', mabi3.DEFAULT_LIMIT) or 0),
        keep_melody=bool(d.get('keep_melody', False)),
        flat_volume=bool(d.get('flat_volume', False)),
        retranscribe=bool(d.get('retranscribe', False)),
        volume=int(d.get('volume', 0) or 0),
        harmony_min=str(d.get('harmony_min') or 'auto'),
        climax=int(d.get('climax', 1)) if str(d.get('climax', 1)) in ('0', '1', '2') else 1,
        instrument=d.get('instrument') if d.get('instrument') in mabi3.INSTRUMENTS else 'piano',
        min_freq=float(d['min_freq']) if d.get('min_freq') else None,
        max_freq=float(d['max_freq']) if d.get('max_freq') else None,
    )


def run_job(job_id, params):
    job = JOBS[job_id]

    def cb(msg):
        with LOCK:
            job['log'].append(msg)
    try:
        if job.get('youtube'):                    # YouTube 連結：先抓成 MP3 再照常跑
            mabi3._tls.log = cb
            try:
                job['src'] = mabi3.fetch_youtube(job['youtube'], os.path.dirname(job['src']))
            finally:
                mabi3._tls.log = None
        res = mabi3.run_pipeline(job['src'], params, log_cb=cb)
        with LOCK:
            job['result'] = res
            job['status'] = 'done'
    # 這裡一定要用 BaseException：sys.exit() 丟的是 SystemExit，它不是 Exception 的
    # 子類別，只寫 except Exception 的話執行緒會直接死掉，狀態永遠停在 working，
    # 網頁就一直轉圈也不說原因。
    except BaseException as e:                    # 把錯誤原文給使用者，方便回報
        with LOCK:
            # str(e) or ...：有些例外的訊息是空字串（例如 audioread 的 NoBackendError），
            # 寫成 (e or ...) 沒有用，例外物件永遠是 truthy，會顯示成「失敗：」什麼都沒有。
            job['log'].append('失敗：%s' % (str(e) or type(e).__name__))
            job['error'] = traceback.format_exc()
            job['status'] = 'error'


class Server(ThreadingHTTPServer):
    # Windows 的 SO_REUSEADDR 允許第二個程式綁到同一個埠，兩個伺服器會同時在聽，
    # 請求隨機落到其中一個 —— 改了程式卻還是看到舊版就是這樣來的。關掉它，
    # 重複啟動會直接報錯，比默默跑兩份好。
    allow_reuse_address = False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    # ---- helpers ----
    def send_json(self, obj, code=200):
        if isinstance(obj, dict) and sources_changed():
            obj = dict(obj, stale=True)
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, ctype, download_name=None):
        with open(path, 'rb') as f:
            body = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        if download_name:
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''%s" % download_name)
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        n = int(self.headers.get('Content-Length') or 0)
        return self.rfile.read(n) if n else b''

    # ---- routes ----
    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path in ('/', '/index.html'):
            return self.send_file(os.path.join(HERE, 'index.html'), 'text/html; charset=utf-8')
        if u.path in ('/about', '/about.html'):
            return self.send_file(os.path.join(HERE, 'about.html'), 'text/html; charset=utf-8')
        if u.path == '/api/status':
            job = JOBS.get(qs.get('job', [''])[0])
            if not job:
                return self.send_json({'error': '找不到這個工作'}, 404)
            with LOCK:
                return self.send_json({'status': job['status'], 'log': list(job['log']),
                                       'result': job.get('result'), 'error': job.get('error')})
        if u.path == '/api/download':
            job = JOBS.get(qs.get('job', [''])[0])
            if not job or not job.get('result'):
                return self.send_json({'error': '還沒有結果'}, 404)
            out = job['result']['output']
            from urllib.parse import quote
            return self.send_file(out, 'text/plain; charset=utf-8', quote(os.path.basename(out)))
        self.send_json({'error': 'not found'}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path == '/api/upload':
            name = os.path.basename(unquote(qs.get('name', ['upload'])[0])).replace('\\', '_') or 'upload'
            ext = os.path.splitext(name)[1].lower()
            if ext not in ALLOWED:
                return self.send_json({'error': '不支援的檔案類型：%s（可用：mp3、wav、flac、ogg、mid、mml）' % (ext or '無副檔名')}, 400)
            data = self.read_body()
            if not data:
                return self.send_json({'error': '檔案是空的'}, 400)
            job_id = uuid.uuid4().hex[:10]
            folder = os.path.join(JOBS_DIR, job_id)
            os.makedirs(folder, exist_ok=True)
            src = os.path.join(folder, name)
            with open(src, 'wb') as f:
                f.write(data)
            JOBS[job_id] = {'status': 'working', 'log': ['收到檔案：%s（%.1f MB）' % (name, len(data) / 1e6)],
                            'src': src, 'kind': 'mml' if ext == '.mml' else ('midi' if ext in ('.mid', '.midi') else 'audio'),
                            'created': time.time()}
            # 上傳時就帶上樂器，鼓才不會先被當成一般樂器採譜一遍
            first = {'instrument': qs.get('instrument', [''])[0]}
            threading.Thread(target=run_job, args=(job_id, params_from_json(first)), daemon=True).start()
            return self.send_json({'job': job_id, 'kind': JOBS[job_id]['kind']})
        if u.path == '/api/youtube':
            try:
                req = json.loads(self.read_body().decode('utf-8') or '{}')
            except ValueError:
                return self.send_json({'error': '參數格式錯誤'}, 400)
            url = (req.get('url') or '').strip()
            if not url.startswith(('http://', 'https://')):
                return self.send_json({'error': '請貼一個 http(s) 開頭的連結'}, 400)
            job_id = uuid.uuid4().hex[:10]
            folder = os.path.join(JOBS_DIR, job_id)
            os.makedirs(folder, exist_ok=True)
            JOBS[job_id] = {'status': 'working', 'log': ['準備下載：%s' % url],
                            'src': os.path.join(folder, 'youtube'), 'kind': 'audio',
                            'youtube': url, 'created': time.time()}
            threading.Thread(target=run_job,
                             args=(job_id, params_from_json(req.get('params'))), daemon=True).start()
            return self.send_json({'job': job_id, 'kind': 'audio'})
        if u.path == '/api/render':
            try:
                req = json.loads(self.read_body().decode('utf-8') or '{}')
            except ValueError:
                return self.send_json({'error': '參數格式錯誤'}, 400)
            job = JOBS.get(req.get('job', ''))
            if not job:
                return self.send_json({'error': '找不到這個工作，請重新上傳'}, 404)
            log = []
            try:
                res = mabi3.run_pipeline(job['src'], params_from_json(req.get('params')), log_cb=log.append)
            except BaseException as e:            # 同上：sys.exit 的 SystemExit 也要接住
                return self.send_json({'error': str(e) or type(e).__name__, 'log': log}, 500)
            with LOCK:
                job['result'] = res
            return self.send_json({'result': res, 'log': log})
        self.send_json({'error': 'not found'}, 404)


def main():
    # 只有「看起來像數字」的參數才當埠號，不然 --no-browser 會被拿去 int() 而炸掉
    ports = [a for a in sys.argv[1:] if a.isdigit()]
    # 環境變數優先，方便部署到 Hugging Face Spaces 之類的地方（那邊固定用 7860，
    # 而且一定要綁 0.0.0.0，綁 127.0.0.1 從外面連不進來）。本機預設仍是只綁本機。
    port = int(ports[0]) if ports else int(os.environ.get('PORT') or 8765)
    host = os.environ.get('HOST') or '127.0.0.1'
    os.makedirs(JOBS_DIR, exist_ok=True)
    url = 'http://%s:%d' % ('127.0.0.1' if host in ('0.0.0.0', '::') else host, port)
    try:
        httpd = Server((host, port), Handler)
    except OSError:
        # 已經有一份在跑了。與其報錯，不如直接把瀏覽器開到那一份去，
        # 這樣使用者點兩下 .bat 還是「有反應」。
        print('網頁已經在執行中：%s' % url, flush=True)
        print('（這個視窗可以直接關掉。要整個重開，先關掉原本那個黑色視窗。）', flush=True)
        if '--no-browser' not in sys.argv:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        return
    print('網頁介面已啟動：%s  （關掉這個視窗就會停止）' % url, flush=True)
    if '--no-browser' not in sys.argv and not os.environ.get('NO_BROWSER'):
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
