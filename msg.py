#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""印出中文提示給 .bat 用。

為什麼要多這個檔：cmd.exe 是「邊執行邊按位元組位置讀」批次檔的。批次檔裡同時
有 chcp 65001 和非 ASCII 文字時，換頁碼之後 cmd 會用錯的位移繼續讀，把中文那行
讀成亂碼再當成指令執行，就會冒出像

    '?湔??ai24' 不是內部或外部命令、可執行的程式或批次檔。

這種訊息。所以三個 .bat 一律只用 ASCII，中文全部交給 Python 印。
"""
import sys

MESSAGES = {
    'drag': '請把 MP3、MID 或 MML 檔案拖到「轉換.bat」上面放開。',
    'done': '結果存在輸入檔旁邊的同名 .mml 檔。',
    'installed': '安裝完成！點兩下「啟動網頁.bat」就可以開始用了。',
    'installing': '正在安裝一般套件…',
    'installing_bp': '正在安裝 basic-pitch（用 --no-deps，避免把 numpy 降版、避免拉進 TensorFlow）…',
}


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else ''
    text = MESSAGES.get(key)
    if text is None:
        return
    try:
        print(text)
    except UnicodeEncodeError:                     # 主控台頁碼不支援時的保險
        sys.stdout.buffer.write(text.encode('utf-8', 'replace') + b'\n')


if __name__ == '__main__':
    main()
