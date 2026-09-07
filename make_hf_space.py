# -*- coding: utf-8 -*-
"""把要上傳到 Hugging Face Space 的檔案打包到 hf-space/。

用法：
    python make_hf_space.py

之後改了 mabi3.py 或 index.html，重跑一次這支就好，不用自己記得要複製哪幾個檔。
產出的 hf-space/ 直接整包拖進 Space 的 Files 頁面（或用 git push）。

hf-space/ 有寫在 .gitignore 裡，它只是產物，不進版本庫。
"""
import io
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'hf-space')

# 程式本體，本機和雲端共用同一份
SHARED = ['mabi3.py', 'server.py', 'msg.py', 'index.html', 'about.html']

# 只有雲端要的東西，放在 deploy/ 免得跟本機用的檔案混在一起
DEPLOY = ['app.py', 'packages.txt', 'README.md']


def main():
    # 清內容而不是砍資料夾本身：Windows 上只要有終端機或編輯器把工作目錄
    # 停在 hf-space/ 裡，rmtree 就會 WinError 32（檔案正由另一個程序使用）。
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    for name in os.listdir(OUT):
        path = os.path.join(OUT, name)
        shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)

    for name in SHARED:
        shutil.copy2(os.path.join(HERE, name), os.path.join(OUT, name))
    for name in DEPLOY:
        shutil.copy2(os.path.join(HERE, 'deploy', name), os.path.join(OUT, name))

    # HF 認的檔名就是 requirements.txt。根目錄那份是本機用的（有 torch，
    # 對免費 Space 太重），所以改拿精簡版並改名。
    shutil.copy2(os.path.join(HERE, 'requirements-hf.txt'),
                 os.path.join(OUT, 'requirements.txt'))

    # Dockerfile 一起帶著，這樣之後想改用 Docker SDK 不用再生一次。
    # 裡面寫的相依檔名要跟著改成 requirements.txt。
    src = io.open(os.path.join(HERE, 'Dockerfile'), encoding='utf-8').read()
    io.open(os.path.join(OUT, 'Dockerfile'), 'w', encoding='utf-8',
            newline='\n').write(src.replace('requirements-hf.txt', 'requirements.txt'))

    files = sorted(os.listdir(OUT))
    total = sum(os.path.getsize(os.path.join(OUT, f)) for f in files)
    print('已產生 %s（%d 個檔案，%.0f KB）：' % (OUT, len(files), total / 1024.0))
    for f in files:
        print('  %s' % f)
    print('把這些整包上傳到 Space 就好。')


if __name__ == '__main__':
    main()
