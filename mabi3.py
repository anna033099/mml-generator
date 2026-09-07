#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mabi3.py — 一首歌（MP3 / YouTube / MIDI / 現成 MML）→《倩女幽魂》編曲用的三軌 MML

    python mabi3.py 歌.mp3            # MP3 / WAV → 採譜 → 三軌 MML（結果存成 歌.mml）
    python mabi3.py 歌.mid            # 已有 MIDI → 三軌 MML
    python mabi3.py 歌.mml            # 別人寫好的 MML → 重新編成三軌

遊戲的編曲介面有 音軌A / 音軌B / 音軌C 三個欄位，每軌上限 3000 字，三軌會同時播放。
所以三軌是「一起組成一首曲子」，不是主旋律配伴奏。

常用選項：
    --instrument piano  目標樂器（piano/zither/harp/eguitar/flute/violin/drums）
    --bpm 92            自動抓的速度不對時，直接指定
    --octave-shift -1   整體高／低一個八度
    --limit 3000        每軌字數上限，同時也是「豐富度預算」：調大自動變豐富
    --volume -3         整體音量增減
    --harmony-min 1/8   B／C 軌保留的最短音；auto = 交給字數預算決定
    --climax 2          副歌讓路強度：主旋律衝高音時讓 B／C 退開（0=關/1=標準/2=強）
    --min-vel 20        丟掉力度低於此值的音（採譜雜音通常很小聲）
    --grid 3            每拍分 3 格（三連音為主的歌）；預設 4 格
    --retranscribe      已經採譜過時，強制重新採譜

輸出：三軌各自一段 MML，分別貼進遊戲的 音軌A／音軌B／音軌C，
      並把遊戲的「音速」旋鈕轉到程式印出來的那個數字。
（指令版仍會印出 MML@A,B,C; 這種合併格式方便存檔；遊戲欄位請貼單軌，
  因為遊戲不收 @ 和逗號這些字元。）
"""
import re
import os
import sys
import math
import argparse
import copy
from fractions import Fraction as F
from collections import Counter

# ====================== 共用：MML 基本定義 ======================
PC = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}
NAMES = ['c', 'c+', 'd', 'd+', 'e', 'f', 'f+', 'g', 'g+', 'a', 'a+', 'b']
MIDI_TO_MABI = -12          # MIDI 60（中央 C）= 瑪奇 o4c = n48
MABI_LOW, MABI_HIGH = 12, 96    # o1c ～ o8c（遊戲編曲鍵盤就是 C1～C8）
DEFAULT_LIMIT = 3000

TOKEN = re.compile(
    r"(?P<cmd>[tvlon])(?P<num>\d+)(?P<dots>\.*)"
    r"|(?P<note>[a-g])(?P<acc>[+#\-]?)(?P<len>\d*)(?P<ndots>\.*)"
    r"|(?P<rest>r)(?P<rlen>\d*)(?P<rdots>\.*)"
    r"|(?P<shift>[<>])"
    r"|(?P<tie>&)"
    r"|(?P<junk>.)"
)


import threading
_tls = threading.local()


class MabiError(Exception):
    """使用者看得懂的錯誤。指令版印出訊息就好，網頁版要能被工作執行緒接住。

    （以前這些地方直接呼叫 sys.exit()，但 SystemExit 不是 Exception 的子類別，
      在 server.py 的工作執行緒裡不會被接住，網頁會一直轉圈卻不顯示原因。）
    """


def log(*a):
    cb = getattr(_tls, 'log', None)
    msg = ' '.join(str(x) for x in a)
    if cb:
        cb(msg)
    else:
        print(msg, file=sys.stderr, flush=True)


def length_value(L, dots):
    base = F(1, L)
    total, add = base, base
    for _ in range(dots):
        add /= 2
        total += add
    return total


def parse_frac(s):
    s = str(s).strip()
    return F(s) if '/' in s else F(float(s))


# ====================== 讀 MML（erinn.tw 六軌 / 別人寫好的譜） ======================
def clean_mml_text(text):
    """把別人寫好的譜清乾淨：拿掉 /*M 12 */ 小節註解、@0 這種樂器指令、隱藏字元。

    遊戲的樂譜欄不收這些字元（會跳「含有不合規字元」），而且我們的解析器也讀不懂。
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)      # /*M 0 */ 之類的註解
    text = re.sub(r'//[^\n]*', '', text)                   # 行註解
    text = re.sub(r'@\s*\d+', '', text)                    # @0、@25 樂器指令
    text = re.sub(r'[\u200b-\u200d\ufeff]', '', text)    # 零寬空白、BOM
    return text


def split_tracks(text):
    text = clean_mml_text(text).strip()
    if 'mml@' in text.lower():
        i = text.lower().index('mml@')
        text = text[i + 4:].split(';')[0]
        return text.split(',') if ',' in text else [text]
    if ',' in text:
        return text.split(',')
    # 有些譜（例如天谕、erinn.tw 複製出來的）用單獨一行的 A / B / C 當軌名分隔
    if re.search(r'^\s*[A-Fa-f]\s*$', text, flags=re.M):
        parts = re.split(r'^\s*[A-Fa-f]\s*$', text, flags=re.M)
        parts = [p for p in parts if p.strip()]
        if parts:
            return parts
    lines = [l for l in text.splitlines() if l.strip()]
    return lines if len(lines) > 1 else [text]


def parse_mml_track(s):
    s = re.sub(r'\s+', '', s).lower()
    notes, tempos = [], []
    octave, deflen, vol = 4, F(1, 4), 8
    t = F(0)
    tie, last = False, None

    def add_note(pitch, dur):
        nonlocal t, tie, last
        if tie and last is not None and last['p'] == pitch and last['e'] == t:
            last['e'] = t + dur
        else:
            last = {'s': t, 'e': t + dur, 'p': pitch, 'v': vol}
            notes.append(last)
        t += dur
        tie = False

    for m in TOKEN.finditer(s):
        if m.group('cmd'):
            c, num, dots = m.group('cmd'), int(m.group('num')), len(m.group('dots'))
            if c == 't':
                tempos.append((t, num))
            elif c == 'v':
                vol = num
            elif c == 'l':
                deflen = length_value(num, dots)
            elif c == 'o':
                octave = num
            elif c == 'n':
                add_note(num, deflen)
        elif m.group('note'):
            acc = m.group('acc')
            pitch = octave * 12 + PC[m.group('note')] + (1 if acc in ('+', '#') else 0) - (1 if acc == '-' else 0)
            if m.group('len'):
                dur = length_value(int(m.group('len')), len(m.group('ndots')))
            else:
                dur, add = deflen, deflen
                for _ in range(len(m.group('ndots'))):
                    add /= 2
                    dur += add
            add_note(pitch, dur)
        elif m.group('rest'):
            dur = length_value(int(m.group('rlen')), len(m.group('rdots'))) if m.group('rlen') else deflen
            t += dur
            tie, last = False, None
        elif m.group('shift'):
            octave += 1 if m.group('shift') == '>' else -1
        elif m.group('tie'):
            tie = True
    return notes, tempos


def load_mml(path):
    tracks = split_tracks(open(path, encoding='utf-8').read())
    per_track, tempos = [], []
    for tr in tracks:
        ns, ts = parse_mml_track(tr)
        per_track.append(ns)
        tempos += ts
    log('讀入 MML %d 軌，共 %d 個音' % (len(tracks), sum(len(x) for x in per_track)))
    return per_track, sorted(set(tempos))


# ====================== 讀 MIDI ======================
def read_midi(path):
    try:
        import mido
    except ImportError:
        raise MabiError('缺少 mido 套件，請先執行： pip install -r requirements.txt')
    mid = mido.MidiFile(path)
    tpb = mid.ticks_per_beat
    tempo = 500000
    tick, sec = 0, 0.0
    on, notes, tempos = {}, [], []
    for msg in mido.merge_tracks(mid.tracks):
        tick += msg.time
        sec += mido.tick2second(msg.time, tpb, tempo)
        if msg.type == 'set_tempo':
            tempo = msg.tempo
            tempos.append((tick, 60e6 / tempo))
        elif msg.type == 'note_on' and msg.velocity > 0:
            if msg.channel == 9:            # 鼓
                continue
            key = (msg.channel, msg.note)
            retrig = False
            if key in on:                   # 同一個音還沒放開就再按：前一個音在這裡結束
                st, ss, v, _ = on.pop(key)
                notes.append({'st': st, 'et': tick, 's': ss, 'e': sec, 'p': msg.note, 'vel': v})
                retrig = True
            on[key] = (tick, sec, msg.velocity, retrig)
        elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
            key = (msg.channel, msg.note)
            if key in on:
                st, ss, v, retrig = on[key]
                if retrig:                  # 這個 off 是屬於前一個（已結束的）音，忽略
                    on[key] = (st, ss, v, False)
                    continue
                on.pop(key)
                notes.append({'st': st, 'et': tick, 's': ss, 'e': sec, 'p': msg.note, 'vel': v})
    for key, (st, ss, v, _) in on.items():
        notes.append({'st': st, 'et': tick, 's': ss, 'e': sec, 'p': key[1], 'vel': v})
    notes = [n for n in notes if n['e'] > n['s']]
    return notes, tempos, tpb


def looks_quantized(notes, tpb):
    """MIDI 若是用軟體排出來的（音符都貼在格線上），就不必重新抓速度。"""
    if not notes:
        return False
    hits = 0
    for n in notes:
        for div in (16, 12):
            unit = tpb / div
            r = (n['st'] % unit)
            if min(r, unit - r) <= tpb / 96:
                hits += 1
                break
    return hits / len(notes) >= 0.95


# ====================== 從「演奏時間」抓速度、對齊格線 ======================
def cluster_onsets(notes, tol=0.04):
    notes.sort(key=lambda n: n['s'])
    clusters = []
    for i, n in enumerate(notes):
        if clusters and n['s'] - clusters[-1]['t0'] <= tol:
            clusters[-1]['idx'].append(i)
        else:
            clusters.append({'t0': n['s'], 'idx': [i]})
    for c in clusters:
        c['t'] = sum(notes[i]['s'] for i in c['idx']) / len(c['idx'])
    return clusters


def estimate_unit(times, g):
    """找一個最小格長 unit，讓相鄰起音的間隔盡量都是 unit 的整數倍。回傳秒。"""
    iois = [b - a for a, b in zip(times, times[1:]) if 0.05 < b - a < 1.2]
    if len(iois) < 8:
        return 60.0 / 100 / g
    cands = {}
    bpm = 55.0
    while bpm <= 190.0:
        unit = 60.0 / bpm / g
        cands[round(bpm, 2)] = sum(abs(d / unit - round(d / unit)) for d in iois) / len(iois)
        bpm += 0.25
    best_bpm = min(cands, key=cands.get)
    half = round(best_bpm / 2 * 4) / 4                  # 沒有十六分音符時，用慢一倍的速度寫比較省字
    if half in cands and cands[half] <= cands[best_bpm] + 0.01:
        best_bpm = half
    return 60.0 / best_bpm / g


def quantize_performance(notes, g, bpm=None, alpha=0.02, beta=0.2):
    """把演奏時間（秒）貼到格線上（鎖相：格線只跟著實際起音「修正一半」，不會被單一個彈早/彈晚的音拖走）。
    回傳 (bpm, beat_units)，並在每個音寫入 qs/qe（格數）。"""
    clusters = cluster_onsets(notes)
    times = [c['t'] for c in clusters]
    unit0 = 60.0 / bpm / g if bpm else estimate_unit(times, g)
    # 第二次分群：琶音式和弦（幾個音前後差幾十毫秒）要當成同一時刻
    clusters = cluster_onsets(notes, tol=min(0.45 * unit0, 0.15))
    unit, pos, grid_t = unit0, 0, clusters[0]['t']
    units = [unit0]
    clusters[0]['pos'], clusters[0]['unit'] = 0, unit0
    for c in clusters[1:]:
        d = c['t'] - grid_t
        k = int(round(d / unit))
        if k >= 1:
            err = c['t'] - (grid_t + k * unit)
            grid_t = grid_t + k * unit + beta * err
            if abs(err) < 0.3 * unit:
                unit = min(max(unit + alpha * err / k, 0.8 * unit0), 1.25 * unit0)
            pos += k
        c['pos'], c['unit'] = pos, unit
        units.append(unit)
    for c in clusters:
        for i in c['idx']:
            nt = notes[i]
            dur = max(1, int(round((nt['e'] - nt['s']) / c['unit'])))
            nt['qs'], nt['qe'] = c['pos'], c['pos'] + dur
    mean_unit = sum(units) / len(units)
    beat_units = g
    est_bpm = bpm if bpm else 60.0 / (mean_unit * beat_units)
    while est_bpm < 50 and beat_units > 1:
        beat_units //= 2
        est_bpm *= 2
    while est_bpm > 200:
        beat_units *= 2
        est_bpm /= 2
    return int(round(est_bpm)), beat_units


def midi_to_notes(path, args):
    raw, tempos_tick, tpb = read_midi(path)
    log('讀入 MIDI：%d 個音' % len(raw))
    raw = [n for n in raw if n['vel'] >= args.min_vel and (n['e'] - n['s']) >= args.min_dur]
    if not raw:
        raise MabiError('過濾後沒有音符了：這個檔案裡的音都太小聲或太短。'
                        '把「雜音門檻」往左拉低（指令版用 --min-vel 0）再試一次。')
    quantized = looks_quantized(raw, tpb) and not args.force_quantize
    out = []
    if quantized:
        log('MIDI 音符已在格線上，直接換算。')
        for n in raw:
            out.append({'s': F(n['st'], 4 * tpb), 'e': F(n['et'], 4 * tpb), 'p': n['p'], 'vel': n['vel']})
        tempos = sorted(set((F(t, 4 * tpb), int(round(b))) for t, b in tempos_tick)) or [(F(0), 120)]
    else:
        bpm, beat_units = quantize_performance(raw, args.grid, args.bpm)
        log('演奏型 MIDI，抓到的速度約 t%d（不對的話用 --bpm 指定）' % bpm)
        for n in raw:
            out.append({'s': F(n['qs'], 4 * beat_units), 'e': F(n['qe'], 4 * beat_units), 'p': n['p'], 'vel': n['vel']})
        tempos = [(F(0), bpm)]
    prof = INSTRUMENTS.get(getattr(args, 'instrument', 'piano')) or INSTRUMENTS['piano']
    lo, hi = prof['range'] or (MABI_LOW, MABI_HIGH)
    for n in out:
        n['p'] = to_mabi_pitch(n['p'], args.octave_shift, lo, hi)
        n['v'] = vel_to_v(n['vel'])
    return out, tempos


def to_mabi_pitch(midi, octave_shift=0, lo=MABI_LOW, hi=MABI_HIGH):
    """MIDI 音高 → 瑪奇音高，並摺回 [lo, hi] 音域內（超出的以八度為單位搬回來）。
    lo/hi 給目標樂器的音域：笛子吹不出低音、低音提琴沒有高音，硬寫進去在遊戲裡是沒聲音的。"""
    p = midi + MIDI_TO_MABI + 12 * octave_shift
    while p < lo:
        p += 12
    while p > hi:
        p -= 12
    return p


def vel_to_v(vel):
    v = int(round(vel / 127.0 * 15))
    v = int(round(v / 3.0)) * 3                        # 只用 3/6/9/12/15 五級，省字數
    return min(15, max(3, v))


# 每個聲部自己的音量帶：主旋律最大聲，低音次之，中聲部墊在底下當背景。
# 分開音量帶，三軌疊起來才聽得出主次；全部同一個音量會糊成一片。
VOICE_VOL = ((11, 15), (10, 14), (11, 15))
# 帶內每幾階換一次音量。中聲部只是背景，用大階距讓它幾乎不換音量：
# 一來不跟主旋律搶耳朵，二來每換一次音量要花 3 個字，中聲部音最多、最省得到。
VOICE_VOL_STEP = (2, 4, 2)


def _smooth_velocity(vels, window):
    """移動中位數。讓音量以「樂句」為單位變化，而不是每個音都跳一次。

    每換一次音量要花 3 個字（例如 v13）。音多的曲子若逐音變化，光音量就吃掉
    上千字，撐爆上限之後整軌被壓平，反而完全沒有強弱。抹平後既省字又更像演奏。
    """
    if window <= 1 or len(vels) <= 2:
        return list(vels)
    half = max(1, window // 2)
    out = []
    for i in range(len(vels)):
        seg = sorted(vels[max(0, i - half): i + half + 1])
        out.append(seg[len(seg) // 2])
    return out


def velocity_range(voices):
    """整首歌的力度分佈（10% / 90% 分位）。採譜模型輸出的力度很保守
    （實測只有 18～106，不是 0～127），要用這首自己的範圍正規化才推得上音量。"""
    vels = sorted(n['vel'] for v in voices for n in v if n.get('vel'))
    if len(vels) < 8:
        return None
    lo, hi = vels[int(len(vels) * 0.10)], vels[int(len(vels) * 0.90)]
    return (lo, hi if hi > lo else lo + 1)


def apply_voice_dynamics(voice, i, window, vol_shift, vrange):
    """把一軌的力度攤到這個聲部自己的音量帶上（就地改 n['v']）。

    vrange 是 None ＝整份來源都沒有力度資料，也就是「貼上現成 MML」的情況。
    那些音量是原作者一個一個寫出來的，這裡一律不動——包括副歌讓路的音量調整。
    （試過對 MML 來源也套用抬升，《梦回还》的 A 軌平均音量會從 12.1 變成 15.0，
    原作者寫的強弱整片被抹平。刻意不做。）
    """
    if not vrange:
        return
    lo, hi = vrange
    vmin, vmax = VOICE_VOL[i]
    vmin = min(15, max(1, vmin + vol_shift))           # 網頁的「整體音量」滑桿
    vmax = min(15, max(vmin, vmax + vol_shift))
    step = VOICE_VOL_STEP[i]
    smooth = _smooth_velocity([n.get('vel', 0) for n in voice], window)
    for n, sv in zip(voice, smooth):
        if not n.get('vel'):                           # MML 來源：本來就有音量，別動
            continue
        t = min(1.0, max(0.0, (sv - lo) / float(hi - lo)))
        v = vmin + t * (vmax - vmin)
        if n.get('hold'):
            n['v'] = int(vmax)                         # 副歌的主旋律：鎖在最大音量
            continue
        v = vmin + round((v - vmin) / step) * step
        # 副歌讓路：退到背景。這裡是「絕對音量單位」，不是音量帶的階距——
        # 乘上 step 的話 B 軌一次就降 8，而 B 的音量帶只有 10~14 寬，會直接壓到聽不見。
        v -= n.get('duck', 0)
        n['v'] = int(min(15, max(1, min(vmax, v))))


def transcribe_basic_pitch(audio_path, mid_path, min_freq=None, max_freq=None,
                           onset=0.5, frame=0.3, min_note_ms=127.7):
    """Spotify Basic Pitch（github.com/spotify/basic-pitch），走套件內附的 ONNX 模型。

    這個環境的 TensorFlow 是用 numpy 1.x 編的，在 numpy 2 底下 import 會丟 AttributeError，
    而 basic_pitch 的偵測只接 ImportError，整包會被弄掛。把 sys.modules['tensorflow']
    暫時設成 None，`import tensorflow` 就會丟 ImportError，basic_pitch 便自動選 ONNX。
    ONNX 模型只有 228 KB、附在套件裡，不必另外下載，CPU 上一首 5 分鐘的歌約 6 秒。
    """
    blocked = 'tensorflow' not in sys.modules
    if blocked:
        sys.modules['tensorflow'] = None
    try:
        try:
            from basic_pitch import FilenameSuffix, build_icassp_2022_model_path
            from basic_pitch.inference import predict
        except ImportError as e:
            raise MabiError('尚未安裝 basic-pitch，請先執行： pip install -r requirements.txt（%s）' % e)
        onnx = build_icassp_2022_model_path(FilenameSuffix.onnx)
        log('採譜中（Basic Pitch）…')
        _, midi, _ = predict(audio_path, model_or_model_path=onnx,
                             onset_threshold=onset, frame_threshold=frame,
                             minimum_note_length=min_note_ms,
                             minimum_frequency=min_freq, maximum_frequency=max_freq)
        midi.write(mid_path)
    finally:
        if blocked and sys.modules.get('tensorflow') is None:
            del sys.modules['tensorflow']


# ====================== 架子鼓：用起音偵測分成大鼓／小鼓／鈸 ======================
# 音高辨識模型不認鼓。這裡不用模型：把頻譜切成三個頻帶，各自偵測起音。
#   kick  = 30~140 Hz 的低頻重擊
#   snare = 150~900 Hz 的中頻爆發（小鼓的「啪」）
#   hihat = 5~12 kHz 的高頻沙沙聲（鈸、hi-hat）
# 三種各自成一軌：第 1 軌大鼓、第 2 軌小鼓、第 3 軌鈸（hi-hat／crash）。
# DRUM_NOTE 是「哪一種鼓寫成哪個音」——遊戲裡架子鼓的音符對應表。
# 以下是預設值（GM 標準鼓組的對應，摺到瑪奇音高），若遊戲實際對應不同，改這張表即可。
DRUM_PITCH = 48                                          # o4c：大鼓／鈸不看音高，寫哪個音都一樣
DRUM_NOTE = {'kick': DRUM_PITCH, 'snare': DRUM_PITCH, 'hihat': DRUM_PITCH}
DRUM_BANDS = (('kick', 30, 140), ('snare', 150, 900), ('hihat', 5000, 12000))


def _pick_peaks(env, delta, wait):
    """純 numpy 的起音挑峰：局部最大值、高於「附近平均 + delta」、彼此至少隔 wait 格。

    不用 librosa.onset.onset_detect：它底層的 peak_pick 走 numba 的 guvectorize，
    在這個環境（numba 0.62 + numpy 2.3 + Windows）會直接 access violation 把程式弄掛。
    """
    import numpy as np
    n = len(env)
    if n < 3:
        return []
    win = max(wait, 8)
    # 附近平均（用累積和算移動平均，避免 O(n*win)）
    cs = np.concatenate([[0.0], np.cumsum(env)])
    lo = np.clip(np.arange(n) - win, 0, n)
    hi = np.clip(np.arange(n) + win + 1, 0, n)
    local_mean = (cs[hi] - cs[lo]) / np.maximum(hi - lo, 1)
    is_peak = (env[1:-1] >= env[:-2]) & (env[1:-1] > env[2:])
    cand = np.where(is_peak & (env[1:-1] >= local_mean[1:-1] + delta))[0] + 1
    out, last = [], -10 ** 9
    for f in cand:
        if f - last >= wait:
            out.append(int(f))
            last = f
        elif env[f] > env[out[-1]]:            # 同一群裡挑最強的那一下
            out[-1] = int(f)
            last = f
    return out


def transcribe_drums(audio_path):
    """回傳 [{'s': 秒, 'e': 秒, 'p': 瑪奇音高, 'vel': 1~127, 'kind': ...}]。"""
    import numpy as np
    try:
        import librosa
    except ImportError:
        raise MabiError('缺少 librosa 套件，請先執行： pip install -r requirements.txt')
    log('讀音檔…')
    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    hop = 256
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    log('偵測鼓點（大鼓／小鼓／鈸）…')
    events = []
    for kind, lo, hi in DRUM_BANDS:
        m = (freqs >= lo) & (freqs < hi)
        sub = librosa.amplitude_to_db(S[m] + 1e-9, ref=np.max)
        env = librosa.onset.onset_strength(S=sub, sr=sr, hop_length=hop)
        if env.max() <= 0:
            continue
        frames = _pick_peaks(env, delta=0.15 * env.max(), wait=int(0.06 * sr / hop))
        peak = np.percentile(env[frames], 95) if len(frames) else 1.0
        for f in frames:
            t = float(librosa.frames_to_time(f, sr=sr, hop_length=hop))
            vel = int(round(30 + 97 * min(1.0, env[f] / max(peak, 1e-9))))
            events.append({'s': t, 'e': t + 0.12, 'p': DRUM_NOTE[kind], 'vel': vel, 'kind': kind,
                           'str': float(env[f] / max(peak, 1e-9))})
    # 小鼓的「啪」在低頻帶也會被聽成大鼓、大鼓在中頻帶也會被聽成小鼓：
    # 同一時刻（30 ms 內）同時偵測到大鼓與小鼓時，只留相對強度高的那一個。
    drop = set()
    kicks = [e for e in events if e['kind'] == 'kick']
    for sn in (e for e in events if e['kind'] == 'snare'):
        for k in kicks:
            if abs(k['s'] - sn['s']) <= 0.03:
                drop.add(id(k) if k['str'] < sn['str'] else id(sn))
    events = [e for e in events if id(e) not in drop]
    events.sort(key=lambda n: n['s'])
    log('鼓點：%s' % '、'.join('%s %d' % (k, sum(1 for e in events if e['kind'] == k)) for k, _, _ in DRUM_BANDS))
    if not events:
        raise MabiError('聽不出任何鼓點。這段音檔裡可能沒有鼓，或鼓聲太小。')
    return events


def drums_to_voices(events, args):
    """鼓點 → 三軌（hi-hat／小鼓／大鼓），各自貼到格線上。"""
    if not events:
        return [[], [], []]
    bpm, beat_units = quantize_performance(events, args.grid, args.bpm)
    log('鼓的速度約 t%d（不對的話手動指定）。第 1、2 軌貼給「大鼓」、第 3 軌貼給「鈸」。' % bpm)
    order = ('kick', 'snare', 'hihat')
    voices = [[], [], []]
    for n in events:
        i = order.index(n['kind'])
        note = {'s': F(n['qs'], 4 * beat_units), 'e': F(n['qs'] + 1, 4 * beat_units),
                'p': n['p'], 'vel': n['vel'], 'v': vel_to_v(n['vel'])}
        voices[i].append(note)
    voices = [monophonic(dedupe(v)) for v in voices]
    return voices, [(F(0), bpm)]


def transcribe_audio(audio_path, mid_path, args=None):
    transcribe_basic_pitch(
        audio_path, mid_path,
        min_freq=getattr(args, 'min_freq', None) or None,
        max_freq=getattr(args, 'max_freq', None) or None)
    log('採譜完成，MIDI 存在：' + os.path.basename(mid_path))


# ====================== YouTube 連結 → MP3 ======================
def _ffmpeg_dir():
    """yt-dlp 只認檔名叫 ffmpeg(.exe) 的執行檔；imageio-ffmpeg 附的那支名字不一樣，
    所以複製一份成標準名字放在專案的 .bin/ 底下（只做一次）。"""
    import shutil
    found = shutil.which('ffmpeg')
    if found:
        return os.path.dirname(found)
    try:
        import imageio_ffmpeg
    except ImportError:
        raise MabiError('要用 YouTube 連結需要 ffmpeg，請先執行： pip install -r requirements.txt')
    src = imageio_ffmpeg.get_ffmpeg_exe()
    dst_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.bin')
    dst = os.path.join(dst_dir, 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    if not os.path.exists(dst):
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copy2(src, dst)
    return dst_dir


def fetch_youtube(url, folder):
    """把 YouTube 連結抓成 MP3，回傳檔案路徑。"""
    try:
        import yt_dlp
    except ImportError:
        raise MabiError('尚未安裝 yt-dlp，請先執行： pip install -r requirements.txt')
    log('讀取 YouTube 連結…')
    opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(folder, '%(title).70s.%(ext)s'),
        'ffmpeg_location': _ffmpeg_dir(),
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3',
                            'preferredquality': '192'}],
        'quiet': True, 'no_warnings': True, 'noprogress': True, 'noplaylist': True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        raise MabiError('YouTube 下載失敗：%s' % e)
    title = info.get('title') or 'youtube'
    for f in sorted(os.listdir(folder)):
        if f.lower().endswith('.mp3'):
            log('下載完成：%s' % title)
            return os.path.join(folder, f)
    raise MabiError('YouTube 下載後找不到 MP3 檔')


# ====================== 樂器設定 ======================
# 倩女幽魂的編曲介面：每個樂器都有 音軌A / 音軌B / 音軌C 三軌，會同時播放。
# 三軌是「一起組成一首曲子」，不是主旋律加伴奏，所以三軌都要寫得有內容。
#
# range   ：這個樂器發得出聲音的音域（None = 用全域的 o1c~o8c）；超出的音會摺回音域內。
# voice   ：網頁試聽用哪一種合成音色。
# sustain / step_ok：見 pick_extreme，擋住左手琶音爬進 A 軌。要設小，設大會把旋律挖出洞。
# fill    ：每軌至少補多長的空隙讓音連起來。補太長會讓兩軌的音重疊、產生半音打架，
#           所以彈撥類補短一點；管樂弦樂要連奏，補長一點。
# drums   ：走鼓的流程（起音偵測），不做音高分軌。
INSTRUMENTS = {
    'piano':   dict(name='鋼琴',   voice='piano',   range=None,     sustain=F(1, 16), step_ok=7,
                    fill=(F(1, 8), F(1, 16), F(1, 16))),
    'zither':  dict(name='瑤箏',   voice='pluck',   range=None,     sustain=F(1, 16), step_ok=7,
                    fill=(F(1, 8), F(1, 16), F(1, 16))),
    'harp':    dict(name='箜篌',   voice='harp',    range=None,     sustain=F(1, 16), step_ok=7,
                    fill=(F(1, 8), F(1, 16), F(1, 16))),
    'eguitar': dict(name='電吉他', voice='eguitar', range=None,     sustain=F(1, 16), step_ok=7,
                    fill=(F(1, 8), F(1, 16), F(1, 16))),
    'flute':   dict(name='笛子',   voice='flute',   range=(36, 96), sustain=F(1, 16), step_ok=7,
                    fill=(F(1, 4), F(1, 4), F(1, 4))),
    'violin':  dict(name='小提琴', voice='violin',  range=(31, 96), sustain=F(1, 16), step_ok=7,
                    fill=(F(1, 4), F(1, 4), F(1, 4))),
    'bass':    dict(name='貝斯',   voice='bass',    range=(16, 60), sustain=F(1, 16), step_ok=7,
                    fill=(F(1, 8), F(1, 8), F(1, 8))),
    'drums':   dict(name='架子鼓', voice='drums',   range=None,     sustain=F(0), step_ok=99,
                    fill=(F(0), F(0), F(0)), drums=True),
}


# ====================== 重新分成三聲部 ======================
def dedupe(notes):
    best = {}
    for n in notes:
        k = (n['s'], n['p'])
        if k not in best or n['e'] > best[k]['e']:
            best[k] = n
    return sorted(best.values(), key=lambda n: (n['s'], -n['p']))


def groups_by_start(notes):
    out, cur, cs = [], [], None
    for n in notes:
        if n['s'] != cs:
            if cur:
                out.append(cur)
            cur, cs = [], n['s']
        cur.append(n)
    if cur:
        out.append(cur)
    return out


def pick_extreme(pool, high, sustain=F(0), step_ok=99):
    """每一刻最高（或最低）的音：一個音開始時，沒有任何還在響的音比它更高（低），才選它。

    sustain / step_ok：選中的音至少「當作」還在響 sustain 這麼久。採譜出來的音常常比
    實際短（Basic Pitch 尤其不會算延音踏板），主旋律的長音一「斷」，底下左手的琶音
    就會被當成最高音搶進主旋律，整首變成一連串十六分音符的咚咚咚。
    在這段延長期間裡，只擋「掉下去一大截（>= step_ok 個半音）」的新音；
    級進下行的旋律（差 1～2 個半音）照樣放行，不會把真正的旋律吃掉。

    延長時間要「短」。曾經設成 1/2 全音符（t59 時約兩秒），結果主旋律被擋掉四成、
    出現 40 個超過一拍的洞，聽起來就是旋律斷斷續續、跟其他兩軌對不上。
    """
    sign = 1 if high else -1
    chosen, chosen_ids, active = [], set(), []          # active: (真正結束, 視為結束, 音高)
    for grp in groups_by_start(pool):
        t = grp[0]['s']
        active = [a for a in active if a[1] > t]
        top = max(grp, key=lambda n: sign * n['p'])
        vetoed = False
        for real_end, eff_end, p in active:
            if real_end > t and sign * p > sign * top['p']:
                vetoed = True
                break
            if eff_end > t and sign * (p - top['p']) >= step_ok:
                vetoed = True
                break
        if not vetoed:
            n = max([x for x in grp if x['p'] == top['p']], key=lambda x: x['e'])
            chosen.append(n)
            chosen_ids.add(id(n))
            active.append((n['e'], max(n['e'], n['s'] + sustain), n['p']))
        for n in grp:
            if id(n) not in chosen_ids:
                active.append((n['e'], n['e'], n['p']))
    return chosen, [n for n in pool if id(n) not in chosen_ids]


def drop_outliers(voice, jump=12, max_len=F(1, 24)):
    """丟掉又短、又孤立、比前後都高（或低）一大截的音。

    採譜模型會把泛音誤判成一個很高的短音，聽起來就是中間突然「嗶」一聲。
    """
    v = sorted(voice, key=lambda n: n['s'])
    out = []
    for i, n in enumerate(v):
        if 0 < i < len(v) - 1 and n['e'] - n['s'] <= max_len:
            up = n['p'] - v[i - 1]['p'] >= jump and n['p'] - v[i + 1]['p'] >= jump
            down = v[i - 1]['p'] - n['p'] >= jump and v[i + 1]['p'] - n['p'] >= jump
            if up or down:
                continue
        out.append(n)
    return out


def pick_inner(pool, rule='near'):
    chosen, prev = [], None
    for grp in groups_by_start(pool):
        if rule == 'high' or prev is None:
            n = max(grp, key=lambda n: (n['p'], n['e'] - n['s']))
        elif rule == 'long':
            n = max(grp, key=lambda n: (n['e'] - n['s'], n['p']))
        else:
            n = min(grp, key=lambda n: (abs(n['p'] - prev), -(n['e'] - n['s'])))
        chosen.append(n)
        prev = n['p']
    return chosen


def monophonic(voice):
    voice = sorted(voice, key=lambda n: n['s'])
    out = []
    for i, n in enumerate(voice):
        e = min(n['e'], voice[i + 1]['s']) if i + 1 < len(voice) else n['e']
        if e > n['s']:
            # 'vel' 要留著，分完聲部後 apply_dynamics 還要用原始力度重算音量
            out.append({'s': n['s'], 'e': e, 'p': n['p'], 'v': n['v'], 'vel': n.get('vel', 0)})
    return out


def thin_voice(voice, min_gap):
    """同一軌的相鄰起音至少隔 min_gap，太密的就併進前一個音。

    和聲軌的音幾乎都落在十六分音符上，用「最短音長」去砍是懸崖：門檻一過 1/16
    就一次砍掉八成（字數 3600 直接掉到 660）。改用「起音間隔」才能平順地變稀疏。
    """
    if min_gap <= 0 or not voice:
        return voice
    v = sorted(voice, key=lambda n: n['s'])
    out = [dict(v[0])]
    for n in v[1:]:
        if n['s'] - out[-1]['s'] >= min_gap:
            out.append(dict(n))
        else:
            out[-1]['e'] = max(out[-1]['e'], n['e'])      # 併進前一個音，維持連續
    return out


def drop_short(voice, min_len):
    return voice if min_len <= 0 else [n for n in voice if n['e'] - n['s'] >= min_len]


def fill_rests(voice, max_gap):
    if max_gap <= 0:
        return voice
    out = [dict(n) for n in voice]
    for i in range(len(out) - 1):
        gap = out[i + 1]['s'] - out[i]['e']
        if 0 < gap < max_gap:
            out[i]['e'] = out[i + 1]['s']
    return out


def resolve_clashes(voices, semitones=(1, 11, 13), min_keep=F(1, 32)):
    """把三軌之間「只差一個半音」的重疊音清掉。

    採譜一定會有假音。兩條線同時響、只差半音，在遊戲那種有延音、泛音豐富的
    音色上非常刺耳；網頁試聽用的是很薄的三角波，反而聽不太出來 —— 這就是
    「合成器沒事、進遊戲才怪」的原因。
    優先保留主旋律 A，其次低音 C，最後才是中聲部 B。
    衝突的音先縮短到衝突發生之前，短到不成音了才整個丟掉。
    """
    order = [0, 2, 1]                                   # 優先權由高到低
    for rank, ti in enumerate(order):
        higher = []
        for o in order[:rank]:
            higher.extend(voices[o])
        if not higher:
            continue
        higher.sort(key=lambda n: n['s'])
        out = []
        for n in voices[ti]:
            e = n['e']
            for m in higher:
                if m['s'] >= e:
                    break
                if m['e'] <= n['s']:
                    continue
                if abs(m['p'] - n['p']) in semitones:
                    e = min(e, m['s'])
            if e - n['s'] >= min_keep:
                nn = dict(n)
                nn['e'] = e
                out.append(nn)
        voices[ti] = out
    return voices


# ====================== 副歌讓路 ======================
# 量過使用者實際轉的三首鋼琴 Cover：主旋律的高音段裡，B 軌有 89% 的時間在響，
# 而且音高中位數比主旋律低 24 個半音（整整兩個八度），C 軌更低到 46 個半音；
# 三軌都有八成以上的時間在發聲。也就是說副歌那些本該最突出的高音，底下同時
# 壓著一整片低音，聽起來就是「沒有重點、很亂很雜」。
#
# 為什麼 B 軌會跑到低音區：pick_inner 用的是「跟前一個音最接近」，有慣性。
# 主旋律在副歌往上衝，中聲部留在原地，結果就跑去跟 C 軌擠在一起，中間空掉。
#
# 在遊戲裡比在網頁試聽嚴重，是因為遊戲音色的延音長、低音更厚，會直接蓋掉高音。
#
# 這裡只動 B、C 兩軌，主旋律一個音都不改——改主旋律的方案試過兩次
#（八度平滑、閘控取旋律），量測數字都更好，但實際聽起來音準和旋律反而更糟。
YIELD_HI_PCT = 0.80        # 主旋律音高超過這個分位數就算「高音段」
YIELD_MERGE = F(1, 2)      # 相鄰高音段間隔小於此就併成同一段，避免一直切換
YIELD_PAD = F(1, 16)       # 每段前後各延伸一點，不要在樂句正中間切
INNER_MAX_BELOW = 19       # 高音段裡 B 軌比主旋律低超過這麼多半音就讓路（一個八度又五度）
BASS_MIN_GAP = F(1, 8)     # 高音段裡 C 軌的最小起音間隔：少走動、改拉長音
# 高音段裡 C 軌單音的長度上限。只合併起音的話，音會變得更長、發聲時間反而更高
#（實測 88~95%，等於低音從頭壓到尾）。加上長度上限才會留出空隙。
# 實測 1/4：發聲時間降到 72~89%，字數幾乎沒變（1% 內）；1/8 更空但開始花字數。
BASS_MAX_LEN = F(1, 4)
YIELD_DUCK = (0, 2, 1)     # 高音段裡 B／C 兩軌音量要降幾個單位
# 主旋律在高音段要「推上去」幾個音量單位。量過四首歌，主旋律副歌內外的平均音量
# 分別是 12.6/12.9、13.2/12.7、12.6/12.6、13.2/13.3——等於整首沒有起伏，
# 副歌那些高音跟主歌一樣大聲，聽起來就沒力。採譜出來的力度本來就分不太出段落，
# 再經過 _smooth_velocity 的移動中位數又更平，所以要在這裡補一個抬升。
# 做法是「鎖在音量帶的最大值」而不是「加幾個單位」：段落內不用再換音量，
# 反而比原本更省字（加法版試過，A 軌會超過 3000 字而掉到「單量」那一階，
# 整軌只剩一個音量，副歌內外都變 15，起伏全沒了）。
# 而且固定音量正好就是「很穩、強而有力」該有的樣子。
# 高音段裡，主旋律底下沒有任何 B 軌的音時，補一個「低八度」的支撐音。
# 只讓路不補支撐的話，副歌有 32~61% 的主旋律音底下是空的，高音會變得很單薄。
# 低八度是編曲上讓高音有厚度最常用的手法，而且音名相同，不會影響和聲。
SUPPORT_OCTAVE = True


def melody_high_spans(melody, pct=YIELD_HI_PCT):
    """主旋律的高音段落，回傳 [(起, 迄), ...]。"""
    if len(melody) < 8:
        return []
    ps = sorted(n['p'] for n in melody)
    thr = ps[min(len(ps) - 1, int(len(ps) * pct))]
    spans = []
    for n in sorted(melody, key=lambda n: n['s']):
        if n['p'] < thr:
            continue
        a, b = n['s'] - YIELD_PAD, n['e'] + YIELD_PAD
        if spans and a - spans[-1][1] <= YIELD_MERGE:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    return [(a, b) for a, b in spans]


def _pitch_at(voice, t):
    """t 這一刻正在響的音高；沒有就回傳 None。"""
    for n in voice:
        if n['s'] <= t < n['e']:
            return n['p']
        if n['s'] > t:
            break
    return None


def _mono_keep(notes):
    """跟 monophonic 一樣把重疊的音截斷，但保留 dict 上的其他鍵。

    monophonic 會重建 dict、只留五個欄位，duck / mute / support 這些標記會被丟掉。
    """
    v = sorted(notes, key=lambda n: n['s'])
    out = []
    for i, n in enumerate(v):
        e = min(n['e'], v[i + 1]['s']) if i + 1 < len(v) else n['e']
        if e > n['s']:
            m = dict(n)
            m['e'] = e
            out.append(m)
    return out


def _in_spans(t, spans):
    for a, b in spans:
        if a <= t < b:
            return True
        if t < a:
            break
    return False


def yield_to_melody(voices, level=1, lo=MABI_LOW):
    """副歌高音時讓 B、C 退開。level：0=關、1=標準、2=強。

    lo：目標樂器音域的下限。低八度支撐音是在 midi_to_notes 套完音域之後才產生的，
    會繞過那道檢查——笛子（36~96）的支撐音可能掉到 28，在遊戲裡是沒聲音的。
    """
    if level <= 0 or len(voices) < 3 or not voices[0]:
        return voices
    melody, inner, bass = voices
    spans = melody_high_spans(melody)
    if not spans:
        return voices

    max_below = INNER_MAX_BELOW - (4 if level >= 2 else 0)
    bass_gap = BASS_MIN_GAP * (2 if level >= 2 else 1)
    bass_max = BASS_MAX_LEN / (2 if level >= 2 else 1)

    # B 軌：高音段裡離主旋律太遠的音直接讓路（留成休止），其餘標記降音量
    new_inner, last_mel = [], None
    for n in inner:
        t = n['s']
        if not _in_spans(t, spans):
            new_inner.append(n)
            continue
        mp = _pitch_at(melody, t)
        if mp is None:
            mp = last_mel
        else:
            last_mel = mp
        n = dict(n)
        if mp is not None and mp - n['p'] > max_below:
            # 標記讓路，不直接刪掉。velocity_range 是拿三軌一起算力度分位數的，
            # 真的把音移除會讓分位數位移，連帶改到「完全沒動」的主旋律的音量量化
            #（實測 A 軌字數 2860 -> 2836）。build_track 會在算完音量前濾掉。
            n['mute'] = True
        else:
            n['duck'] = YIELD_DUCK[1]
        new_inner.append(n)

    # C 軌：高音段裡不刪音，改成「少走動」——起音太密的併進前一個音，變成長音
    new_bass, prev_in_span = [], None
    for n in bass:
        if not _in_spans(n['s'], spans):
            new_bass.append(n)
            prev_in_span = None
            continue
        if prev_in_span is not None and n['s'] - prev_in_span['s'] < bass_gap:
            prev_in_span['e'] = max(prev_in_span['e'], n['e'])
            n = dict(n)
            n['mute'] = True                           # 同上，留著讓力度分位數不變
            new_bass.append(n)
            continue
        n = dict(n)
        n['e'] = min(n['e'], n['s'] + bass_max)
        n['duck'] = YIELD_DUCK[2]
        new_bass.append(n)
        prev_in_span = n

    # 主旋律：不動音高、不動節奏，只把高音段的音量推上去。
    # 這是唯一會動到 A 軌的地方，而且只動 n['duck']（負值＝抬升），
    # 音符本身一個都沒改。
    melody = [dict(n, hold=True) if _in_spans(n['s'], spans) else n
              for n in melody]

    if SUPPORT_OCTAVE:
        new_inner = _add_octave_support(melody, new_inner, spans, lo)

    return [melody, new_inner, new_bass]


def _add_octave_support(melody, inner, spans, lo=MABI_LOW):
    """高音段裡主旋律底下空著的地方，用低八度補一個支撐音。

    只讓 B 軌退開、不補支撐的話，副歌有 32~61% 的主旋律音底下完全沒有東西，
    高音就變成孤零零一條線，聽起來很虛。低八度支撐是編曲上讓高音有厚度最直接的
    做法，音名跟主旋律相同，不會改變和聲。
    """
    # 被標成 mute 的音只是留著讓 velocity_range 的分位數不變，不參與位置計算
    audible = [n for n in inner if not n.get('mute')]
    muted = [n for n in inner if n.get('mute')]
    add = []
    for m in melody:
        if not _in_spans(m['s'], spans):
            continue
        mid = m['s'] + (m['e'] - m['s']) / 2
        if _pitch_at(audible, m['s']) is not None or _pitch_at(audible, mid) is not None:
            continue                                   # 底下已經有東西了
        p = m['p'] - 12
        if p < lo:
            continue                               # 掉出樂器音域就不補
        add.append({'s': m['s'], 'e': m['e'], 'p': p, 'v': m['v'],
                    'vel': m.get('vel', 0), 'duck': YIELD_DUCK[1]})
    if not add:
        return inner
    return sorted(_mono_keep(audible + add) + muted, key=lambda n: n['s'])


def reduce_to_three(notes, melody_notes=None, inner_rule='near', vol_shift=0, profile=None,
                    climax=1):
    prof = profile or INSTRUMENTS['piano']
    sus, step = prof['sustain'], prof['step_ok']
    if melody_notes is None:
        pool = dedupe(notes)
        melody, rest = pick_extreme(pool, True, sus, step)
    else:
        melody, rest = dedupe(melody_notes), dedupe(notes)
    bass, rest = pick_extreme(rest, False, sus, step)
    inner = pick_inner(rest, inner_rule)
    melody, inner = drop_outliers(melody), drop_outliers(inner)
    # 音量在 fit_to_limit 那邊才算：每個豐富度階層的平滑程度不同
    voices = [monophonic(melody), monophonic(inner), monophonic(bass)]
    if not prof.get('drums'):
        voices = resolve_clashes(voices)
        voices = yield_to_melody(voices, climax, (prof['range'] or (MABI_LOW, MABI_HIGH))[0])
    return voices


# ====================== 寫成 MML ======================
GRID = F(1, 192)
_std = {}
for L in (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64):
    for val, tok in ((F(1, L), str(L)), (F(3, 2 * L), str(L) + '.')):
        if val < F(1, 64):
            continue
        if val not in _std or len(tok) < len(_std[val]):
            _std[val] = tok
STD = sorted(_std.items(), key=lambda x: -x[0])
MIN_UNIT = F(1, 64)


def decompose(dur):
    parts, remain = [], dur
    for val, tok in STD:
        while remain >= val:
            parts.append(tok)
            remain -= val
    if remain >= MIN_UNIT / 2:
        parts.append('64')
        remain -= MIN_UNIT
    return parts, dur - remain


def q(x):
    return F(round(x / GRID)) * GRID


# 《倩女幽魂》這一系（網易／天谕）的解析器沒有 `l`（預設音長）指令：
# 社群的符號表沒有它、實際流傳的天谕譜每個音都寫明長度、Revelation Mobile 的
# MML 解析器也只認 t o v > < : 和音名。若遊戲忽略 l16，我們寫的裸音符會被當成
# 四分音符 —— 音高全對、節奏全平，聽起來就是整首「咚咚咚」。所以預設不寫 l，
# 每個音、每個休止符都標長度。
USE_L = False


def encode(voice, tempos=None, flat_volume=False, use_l=USE_L):
    tempos = sorted(tempos or [])
    voice = [{'s': q(n['s']), 'e': q(n['e']), 'p': n['p'], 'v': n['v']} for n in voice]
    voice = [n for n in voice if n['e'] > n['s']]
    if not voice:
        return ''
    cnt, cursor = Counter(), F(0)
    for n in voice:
        gap = n['s'] - cursor
        if gap > 0:
            cnt.update(decompose(gap)[0])
        cnt.update(decompose(n['e'] - n['s'])[0])
        cursor = n['e']
    deflen = cnt.most_common(1)[0][0]

    out = []
    if flat_volume:
        # 用 75 百分位而不是中位數：中位數會挑到音量帶的最低階，
        # 整軌被壓平之後聽起來明顯變小聲。
        vols = sorted(n['v'] for n in voice)
        cur_vol = vols[min(len(vols) - 1, int(len(vols) * 0.75))]
    else:
        cur_vol = voice[0]['v']
    out.append('v%d' % cur_vol)
    if use_l:
        out.append('l' + deflen)
    cur_oct = voice[0]['p'] // 12
    out.append('o%d' % cur_oct)
    cursor, pending = F(0), list(tempos)

    def emit_tempos(boundary, end):
        mid = (boundary + end) / 2
        while pending and pending[0][0] <= mid:
            out.append('t%d' % pending.pop(0)[1])

    def emit_len(parts, letter):
        if use_l:
            return [letter + ('' if p == deflen else p) for p in parts]
        return [letter + p for p in parts]

    for n in voice:
        gap = n['s'] - cursor
        if gap > 0:
            parts, real = decompose(gap)
            emit_tempos(cursor, cursor + real)
            out.extend(emit_len(parts, 'r'))
            cursor += real
        dur = n['e'] - cursor
        if dur <= 0:
            continue
        parts, real = decompose(dur)
        if not parts:
            continue
        emit_tempos(cursor, cursor + real)
        if not flat_volume and n['v'] != cur_vol:
            cur_vol = n['v']
            out.append('v%d' % cur_vol)
        octv, pc = n['p'] // 12, n['p'] % 12
        if octv != cur_oct:
            out.append('>' if octv == cur_oct + 1 else '<' if octv == cur_oct - 1 else 'o%d' % octv)
            cur_oct = octv
        out.append('&'.join(emit_len(parts, NAMES[pc])))
        cursor += real
    while pending:
        out.append('t%d' % pending.pop(0)[1])
    return ''.join(out)


# 從「最豐富」到「最精簡」的階梯。fit_to_limit 會挑「塞得進字數上限的最豐富那一階」，
# 所以字數上限本身就是豐富度旋鈕：調大 → 自動選更密的一階；調小 → 自動變簡單。
# （以前上限只是天花板，沒超過就完全不影響結果，調大等於沒作用。）
# 欄位：名稱, 和聲最短音, 音量平滑窗, 補空隙, 音量壓平, 主旋律最短音
RICHNESS = [
    # 從最豐富到最精簡。fit_to_limit 挑「塞得進上限的最豐富那一階」，
    # 所以字數上限就是豐富度旋鈕。
    # 砍字數的順序：先砍音量變化（每次 3 個字）→ 再拉開起音間隔 → 最後才用音長門檻。
    # 欄位：名稱, 和聲最短音, 和聲最小起音間隔, 音量平滑窗, 補空隙, 音量壓平, 主旋律最短音
    ('極豐富',      F(1, 48), F(0),     1, F(1, 64), False, 0),
    ('最豐富',      F(1, 32), F(0),     3, F(1, 32), False, 0),
    ('很豐富',      F(1, 24), F(0),     5, F(1, 32), False, 0),
    ('豐富',        F(1, 16), F(0),     7, F(1, 16), False, 0),
    ('豐富·省量',   F(1, 16), F(0),    15, F(1, 16), False, 0),
    ('豐富·單量',   F(1, 16), F(0),    99, F(1, 8),  True,  0),
    ('稍疏',        F(1, 16), F(1, 12), 11, F(1, 16), False, 0),
    ('稍疏·單量',   F(1, 16), F(1, 12), 99, F(1, 8),  True,  0),
    ('疏',          F(1, 16), F(1, 8),  11, F(1, 16), False, 0),
    ('疏·單量',     F(1, 16), F(1, 8),  99, F(1, 8),  True,  0),
    ('更疏',        F(1, 16), F(1, 6),  99, F(1, 8),  True,  0),
    ('中等',        F(1, 12), F(1, 6),  99, F(1, 8),  True,  0),
    ('簡單',        F(1, 8),  F(1, 4),  99, F(1, 8),  True,  0),
    ('很簡單',      F(1, 6),  F(1, 3),  99, F(1, 4),  True,  0),
    ('最精簡',      F(1, 4),  F(1, 2),  99, F(1, 4),  True,  F(1, 32)),
]

# 每軌至少要把多長的空隙補起來（讓音延續到下一個音）。
# 注意不能補太兇：低音補到 1/2 全音符時，低音軌會變成「從頭到尾都在發聲」，
# 聽起來就是一直有個很低的嗡嗡聲。低音本來就該有換氣和斷點。
VOICE_FILL = (F(1, 2), F(1, 4), F(1, 4))          # 預設（鋼琴）；實際以 INSTRUMENTS[...]['fill'] 為準


def build_track(voice, i, tempos, args, level, vrange):
    """把一軌壓成 MML。level 是 RICHNESS 的一列。"""
    _, hmin, min_gap, window, fill, flat, min_m = level
    flat = flat or args.flat_volume
    user_fill, user_min = parse_frac(args.fill_rest), parse_frac(args.min_len)
    # 「和聲密度」留 auto 就交給階梯決定；使用者手動指定時以使用者為準
    hm = getattr(args, 'harmony_min', 'auto')
    if str(hm).strip() not in ('', 'auto', 'None'):
        hmin = parse_frac(hm)
    mn = (min_m or 0) if i == 0 else max(hmin, user_min)
    x = [dict(n) for n in voice if not n.get('mute')]  # 每一階都從原始音符重算
    x = drop_short(x, mn)
    # B／C 軌照 min_gap 稀疏；主旋律用一半的間隔，只有在階梯降到很簡單時才會動到，
    # 但至少讓「主旋律本身就太密」的曲子還有路可以降，不會卡在超過上限出不來。
    x = thin_voice(x, min_gap if i > 0 else min_gap / 2)
    prof = INSTRUMENTS.get(getattr(args, 'instrument', 'piano'), INSTRUMENTS['piano'])
    x = fill_rests(x, max(fill, prof['fill'][i], user_fill))
    apply_voice_dynamics(x, i, window, args.volume, vrange)
    # 速度要寫進「每一軌」。只寫在 A 軌的話，遊戲裡 B、C 兩軌會用「音速」旋鈕的
    # 預設速度播放，三軌就對不上、聽起來卡卡的。
    return encode(x, tempos, flat)


def fit_to_limit(voices, tempos, args):
    """每一軌各自挑「塞得進上限的最豐富那一階」。

    兩件事：
    1. 三軌分開挑。以前只要有一軌超標，三軌會一起被「音量壓平」，
       連只用了一半字數的主旋律也跟著失去強弱，整首聽起來就沒有起伏。
    2. 上限變成豐富度預算，而不只是天花板：字數給得多就自動塞進更多細節。
    """
    vrange = velocity_range(voices)
    result, used_levels = [], []
    for i, voice in enumerate(voices):
        mml, used = '', RICHNESS[-1][0]
        for level in RICHNESS:
            mml, used = build_track(voice, i, tempos, args, level, vrange), level[0]
            if args.limit <= 0 or len(mml) <= args.limit:
                break
        result.append(mml)
        used_levels.append(used)
    log('字數：%s（上限 %s）' % (' / '.join(str(len(x)) for x in result), args.limit or '不限'))
    log('　豐富度：%s' % ' / '.join('%s %s' % (TRACK_NAMES[i], u) for i, u in enumerate(used_levels)))
    over = [TRACK_NAMES[i] for i, m in enumerate(result) if args.limit > 0 and len(m) > args.limit]
    if over:
        log('警告：%s 簡化到底仍超過上限，建議把曲子截短，或把上限調高。' % '、'.join(over))
    return result


# ====================== 主流程 ======================
DEFAULTS = dict(output=None, limit=DEFAULT_LIMIT, bpm=None, grid=4, octave_shift=0, inner='near',
                keep_melody=False, flat_volume=False, fill_rest='1/32', min_len='0', min_vel=20,
                min_dur=0.04, force_quantize=False, retranscribe=False,
                volume=0, harmony_min='auto', climax=1,
                min_freq=None, max_freq=None, instrument='piano')
TRACK_NAMES = ['音軌A', '音軌B', '音軌C']
AUDIO_EXT = ('.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac')


class Params(argparse.Namespace):
    def __init__(self, **kw):
        d = dict(DEFAULTS)
        d.update({k: v for k, v in kw.items() if v is not None or k in ('bpm', 'output')})
        super().__init__(**d)


def notes_for_display(mml_track):
    """把一軌 MML 解析回音符，給網頁畫鋼琴捲軸與試聽用。時間單位：全音符（浮點）。"""
    ns, _ = parse_mml_track(mml_track)
    return [[float(n['s']), float(n['e'] - n['s']), n['p'], n['v']] for n in ns]


def run_pipeline(src, args=None, log_cb=None):
    """整條流程。src：.mp3/.wav/.mid/.mml；args：Params；log_cb：接收進度文字的函式。回傳 dict。"""
    args = args or Params()
    if log_cb:
        _tls.log = log_cb
    try:
        if not os.path.exists(src):
            raise FileNotFoundError('找不到檔案：' + src)
        base, ext = os.path.splitext(src)
        ext = ext.lower()
        out_path = args.output or (base + ('_3tracks.mml' if ext == '.mml' else '.mml'))
        mid_path = None
        if ext == '.mml':
            per_track, tempos = load_mml(src)
            # 貼上現成的 MML 是別人一個音一個音寫出來的。副歌讓路那一整套
            #（讓路、低八度支撐、主旋律推到最大音量）在這裡一律不套用，
            # 盡量保留原作者寫的東西。音量本來就不會動（見 apply_voice_dynamics），
            # 這裡連音符的取捨也不動。
            if getattr(args, 'climax', 1):
                log('貼上的樂譜：不套用副歌讓路，保留原作者寫的內容')
            args = copy.copy(args)
            args.climax = 0
            if args.keep_melody and len(per_track) > 1:
                voices = reduce_to_three([n for ns in per_track[1:] for n in ns], per_track[0], args.inner,
                                         args.volume, climax=args.climax)
            else:
                voices = reduce_to_three([n for ns in per_track for n in ns], None, args.inner, args.volume,
                                         climax=args.climax)
            kind = 'mml'
        else:
            if ext in AUDIO_EXT and INSTRUMENTS.get(args.instrument, {}).get('drums'):
                voices, tempos = drums_to_voices(transcribe_drums(src), args)
                kind, mid_path = 'audio', None
            elif ext in AUDIO_EXT:
                mid_path = base + '.bp.mid'
                if args.retranscribe or not os.path.exists(mid_path):
                    transcribe_audio(src, mid_path, args)
                else:
                    log('已經採譜過，直接使用')
                src, kind = mid_path, 'audio'
            elif ext in ('.mid', '.midi'):
                mid_path, kind = src, 'midi'
            else:
                raise ValueError('不認識的副檔名：' + ext)
            if mid_path is not None or ext in ('.mid', '.midi'):
                notes, tempos = midi_to_notes(src, args)
                voices = reduce_to_three(notes, None, args.inner, args.volume, INSTRUMENTS.get(args.instrument),
                                         climax=args.climax)
        if INSTRUMENTS.get(args.instrument, {}).get('drums'):
            log('鼓點：大鼓 %d、小鼓 %d、鈸 %d' % tuple(len(v) for v in voices))
        else:
            log('分軌後：音軌A %d 音、音軌B %d 音、音軌C %d 音' % tuple(len(v) for v in voices))
        result = fit_to_limit(voices, tempos, args)
        final = 'MML@' + ','.join(result) + ';'
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(final + '\n')
        log('完成！已存到：%s' % out_path)
        return {
            'mml': final, 'output': out_path, 'kind': kind, 'mid_path': mid_path,
            'bpm': tempos[0][1] if tempos else 120,
            'limit': args.limit,
            'tracks': [{'name': TRACK_NAMES[i], 'mml': t, 'chars': len(t), 'notes': notes_for_display(t)}
                       for i, t in enumerate(result)],
        }
    finally:
        if log_cb:
            _tls.log = None


def main():
    ap = argparse.ArgumentParser(description='MP3 / MIDI / 多軌 MML → 三軌瑪奇 MML')
    ap.add_argument('input')
    ap.add_argument('-o', '--output', help='輸出檔名（預設：輸入檔名.mml）')
    ap.add_argument('--limit', type=int, default=DEFAULT_LIMIT)
    ap.add_argument('--bpm', type=float, default=None)
    ap.add_argument('--grid', type=int, default=4, help='每拍分幾格：4=十六分音符（預設），3=三連音，8=三十二分音符')
    ap.add_argument('--octave-shift', type=int, default=0)
    ap.add_argument('--inner', choices=['near', 'high', 'long'], default='near')
    ap.add_argument('--keep-melody', action='store_true')
    ap.add_argument('--flat-volume', action='store_true')
    ap.add_argument('--fill-rest', default='1/32')
    ap.add_argument('--min-len', default='0')
    ap.add_argument('--min-vel', type=int, default=20)
    ap.add_argument('--min-dur', type=float, default=0.04, help='丟掉短於此秒數的音（採譜雜音）')
    ap.add_argument('--force-quantize', action='store_true', help='MIDI 一律重新抓速度對格線')
    ap.add_argument('--retranscribe', action='store_true')
    ap.add_argument('--volume', type=int, default=0, help='整體音量增減（-6~+4），0 = 預設')
    ap.add_argument('--harmony-min', default='auto', help='和聲軌保留的最短音（越小越密、越吵）')
    ap.add_argument('--climax', type=int, choices=[0, 1, 2], default=1,
                    help='副歌讓路：主旋律衝高音時讓 B／C 兩軌退開。0=關、1=標準、2=強')
    ap.add_argument('--instrument', choices=list(INSTRUMENTS), default='piano',
                    help='目標樂器：' + '/'.join('%s=%s' % (k, v['name']) for k, v in INSTRUMENTS.items()))
    ap.add_argument('--min-freq', type=float, default=None, help='basic-pitch：低於這個頻率的音不要（Hz），可去掉低頻雜訊')
    ap.add_argument('--max-freq', type=float, default=None, help='basic-pitch：高於這個頻率的音不要（Hz）')
    args = ap.parse_args()
    try:
        res = run_pipeline(args.input, Params(**vars(args)))
    except (FileNotFoundError, ValueError, MabiError) as e:
        sys.exit(str(e))
    log('（貼到 mml.mabi.tw 或遊戲空白樂譜即可）')
    print(res['mml'])


if __name__ == '__main__':
    main()
