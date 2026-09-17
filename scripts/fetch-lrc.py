#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fetch-lrc.py — 音乐一键入库脚本（Firefly 博客专用）

把音频丢给它，自动完成：
  1. 读取 mp3/m4a/flac 的歌名、歌手、时长（内嵌标签）
  2. 封面：优先音频内嵌封面 → 没有就去网易云/QQ音乐取专辑封面
  3. 歌词：网易云 → QQ音乐 → 酷狗 → lrclib 依次兜底，外语歌自动并入官方中文翻译
  4. 音频按「曲名.扩展名」复制进 public/assets/music/，封面 → cover/，歌词 → lrc/
  5. 追加到底部播放器歌单 src/config/musicConfig.ts，并生成 /music/ 页面条目
     src/content/bangumi/music/<曲名>.md

用法：
  python scripts/fetch-lrc.py "D:/Music/歌.mp3"      # 单个文件（最常用）
  python scripts/fetch-lrc.py "D:/Music/"            # 整个目录批量
  python scripts/fetch-lrc.py "歌名" "歌手" --lyrics-only   # 只重抓歌词
  python scripts/fetch-lrc.py "D:/Music/歌.mp3" --dry-run   # 只预览不写文件

常用开关：
  --lyrics-only     只抓歌词，不下载/复制音频
  --no-translation  不并入中文翻译（默认外语歌自动双语）
  --keep-credits    保留开头的制作人员名单
  --no-proxy        强制直连（默认跟随系统代理）
  --dry-run         只预览，不写任何文件

依赖：pip install mutagen（无需 ffmpeg）
"""

import argparse
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request

try:
    import mutagen
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3
    from mutagen.mp4 import MP4
except ImportError:
    print("缺少 mutagen：先运行  pip install mutagen")
    sys.exit(1)

BLOG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSIC_DIR = os.path.join(BLOG_ROOT, "public", "assets", "music")
COVER_DIR = os.path.join(MUSIC_DIR, "cover")
LRC_DIR = os.path.join(MUSIC_DIR, "lrc")
CONFIG_PATH = os.path.join(BLOG_ROOT, "src", "config", "musicConfig.ts")

METING_API = "https://api.i-meto.com/meting/api?server=:server&type=:type&id=:id"
AUDIO_EXTS = (".m4a", ".mp3", ".flac", ".wav", ".ogg")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 歌词里夹带的制作人员名单特征词（开头那几秒挤一堆，显示时会疯狂闪跳）
CREDIT_RE = re.compile(
    r"作词|作曲|编曲|演唱|混音|母带|录音|监制|出品|制作人|和声|乐器|吉他|助理|"
    r"Lyricist|Composer|Arranger|Vocal|Mixing|Mastering|Produced|Producer|Studio|Engineer",
    re.I,
)
META_RE = re.compile(r"^\[(ti|ar|al|by|offset|length|total|re|ve|kana):", re.I)
_TIME_TOKEN_RE = re.compile(r"^\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]")

_PROXY_OFF = False  # --no-proxy 时置 True


def _opener():
    handlers = []
    if _PROXY_OFF:
        handlers.append(urllib.request.ProxyHandler({}))
    else:
        handlers.append(urllib.request.ProxyHandler())  # 跟随 http(s)_proxy 环境变量
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    handlers.append(urllib.request.HTTPSHandler(context=ctx))
    op = urllib.request.build_opener(*handlers)
    op.addheaders = [("User-Agent", UA)]
    return op


def http_get(url, timeout=15, referer=None):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    if referer:
        req.add_header("Referer", referer)
    with _opener().open(req, timeout=timeout) as r:
        return r.read()


def http_json(url, referer=None):
    return json.loads(http_get(url, referer=referer).decode("utf-8", "ignore"))


def meting(server, mtype, keyword):
    url = METING_API.replace(":server", server).replace(":type", mtype).replace(":id", urllib.parse.quote(keyword))
    return http_json(url)


def sanitize(name):
    """清理文件名里的空格和非法字符，保证 URL 合法"""
    name = re.sub(r'\s+', '-', name.strip())
    return re.sub(r'[\\/:*?"<>|]', '', name)


def _timed_rows(text):
    """把 lrc 文本解析成 [(秒, 原始行)]，只保留带时间戳的行"""
    rows = []
    for line in text.splitlines():
        m = _TIME_TOKEN_RE.match(line.strip())
        if m:
            cs = m.group(3) or "0"
            sec = int(m.group(1)) * 60 + int(m.group(2)) + int(cs) / (1000.0 if len(cs) == 3 else 100.0)
            rows.append((sec, line.strip()))
    return rows


def _lrc_body(line):
    return re.sub(r"^(\[\d{1,2}:\d{1,2}([.:]\d{1,3})?\])+", "", line).strip()


def _ffmpeg_exe():
    """找一个可用的 ffmpeg：优先 imageio-ffmpeg 自带的，其次 PATH 里的"""
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    import shutil
    return shutil.which("ffmpeg")


def convert_to_mp3(src, dest, bitrate="320k"):
    """把 flac/wav 转成 mp3（尽量保留标签和封面）→ (成功?, 说明)"""
    exe = _ffmpeg_exe()
    if not exe:
        return False, "找不到 ffmpeg（可 pip install imageio-ffmpeg）"
    import subprocess
    # 先把封面/标签一起带过去；失败再退回只带音频
    variants = [
        ["-map", "0:a", "-map", "0:v?", "-c:v", "copy", "-disposition:v", "attached_pic"],
        ["-map", "0:a"],
    ]
    last = ""
    for extra in variants:
        cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", "-i", src] + extra + [
            "-map_metadata", "0", "-c:a", "libmp3lame", "-b:a", bitrate,
            "-id3v2_version", "3", dest,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 10240:
            return True, f"已转成 MP3 {bitrate}"
        last = (r.stderr or "").strip()[:200]
        if os.path.exists(dest):
            os.remove(dest)
    return False, f"转换失败：{last}"


def strip_leading_credits(text):
    """去掉开头挤成一团的制作人员名单。
    规则：正文起点 = 第一条「时间>15s 且与上一行间隔>3s」的歌词；
    并校验被删前缀里至少 6 成行含制作关键词，不像名单就不删（防止误删正文）。
    """
    rows = _timed_rows(text)
    if len(rows) < 4:
        return text
    start = 0
    for i in range(1, len(rows)):
        if rows[i][0] > 15 and rows[i][0] - rows[i - 1][0] > 3:
            start = i
            break
    if start < 2:
        return text
    pre = [r[1] for r in rows[:start]]
    hits = sum(1 for ln in pre if CREDIT_RE.search(_lrc_body(ln)))
    if hits < max(2, int(len(pre) * 0.6)):
        return text
    meta = [ln for ln in text.splitlines() if META_RE.match(ln.strip())]
    return "\n".join(meta + [r[1] for r in rows[start:]]) + "\n"


def _norm_text(s):
    return re.sub(r"[^0-9a-z\u3040-\u30ff\u4e00-\u9fff]", "", s.lower())


def fetch_cover(name, artist, want_dur=None):
    """无内嵌封面时自动取专辑封面：网易云 song/detail 优先，QQ音乐 albummid 兜底 → (图片字节, 来源说明)"""
    kw = f"{name} {artist}".strip()

    # ① 网易云：搜索拿 id → song/detail 拿 album.picUrl
    try:
        d = http_json("https://music.163.com/api/search/get?s=%s&type=1&limit=10&offset=0"
                      % urllib.parse.quote(kw), referer="https://music.163.com/")
        for s in ((d.get("result") or {}).get("songs")) or []:
            if (s.get("name") or "").strip() != name:
                continue
            dur = (s.get("duration") or 0) / 1000.0
            if want_dur and abs(dur - want_dur) > 8:
                continue
            sid = s.get("id")
            det = http_json("https://music.163.com/api/song/detail?ids=%%5B%s%%5D" % sid,
                            referer="https://music.163.com/")
            album = ((det.get("songs") or [{}])[0]).get("album") or {}
            pic = album.get("picUrl") or ""
            if pic:
                sep = "&" if "?" in pic else "?"
                return http_get(pic + sep + "param=600y600"), "网易云专辑封面"
            break
    except Exception as e:  # noqa: BLE001
        print(f"  [封面] 网易云取封面失败：{e}")

    # ② QQ音乐：albummid 拼固定格式地址
    try:
        d = http_json("https://c.y.qq.com/soso/fcgi-bin/client_search_cp?w=%s&format=json&n=10&p=1"
                      % urllib.parse.quote(kw), referer="https://y.qq.com/")
        for s in (((d.get("data") or {}).get("song") or {}).get("list") or []):
            if (s.get("songname") or "").strip() != name:
                continue
            if want_dur and abs((s.get("interval") or 0) - want_dur) > 8:
                continue
            mid = s.get("albummid")
            if mid:
                url = f"https://y.qq.com/music/photo_new/T002R500x500M000{mid}.jpg"
                return http_get(url, referer="https://y.qq.com/"), "QQ音乐专辑封面"
            break
    except Exception as e:  # noqa: BLE001
        print(f"  [封面] QQ音乐取封面失败：{e}")

    return None, "未找到封面"



def merge_bilingual(lrc_text, tlyric_text, tolerance=0.05):
    """把译文按时间戳并进原文，生成「原文 (译文)」单行。
    播放器解析时会拆成原文+译文两行分别渲染（MusicManager.parseLRC → splitBilingual）。
    """
    base = _timed_rows(lrc_text)
    tmap = {}
    for sec, line in _timed_rows(tlyric_text):
        t = _lrc_body(line)
        if t:
            tmap[sec] = t
    if not tmap:
        return ""
    out, used = [], set()
    for sec, line in base:
        body = _lrc_body(line)
        if not body:
            continue
        t = tmap.get(sec)
        if t is None:
            for k, v in tmap.items():
                if k not in used and abs(k - sec) <= tolerance:
                    t = v
                    used.add(k)
                    break
        out.append(f"{line} ({t})" if t and t != body and _norm_text(t) != _norm_text(body) else line)
    if not out:
        return ""
    meta = [ln for ln in lrc_text.splitlines() if META_RE.match(ln.strip())]
    return "\n".join(meta + out) + "\n"


def clean_lrc(text):
    """清掉制作名单，只留正片歌词（保留 [ti:] 等元信息行）"""
    text = strip_leading_credits(text)
    out, skipping = [], True
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if META_RE.match(s):
            out.append(line)
            continue
        if not re.match(r"^\[\d{1,2}:\d{1,2}([.:]\d{1,3})?\]", s):
            continue
        if skipping and CREDIT_RE.search(_lrc_body(s)):
            continue  # 开头连续的 作词/作曲/演唱… 行
        skipping = False
        if _lrc_body(s):
            out.append(line)
    if not out:
        return ""
    return "\n".join(out) + "\n"


def _lrc_from_netease(name, artist, want_dur=None):
    kw = f"{name} {artist}".strip()
    d = http_json("https://music.163.com/api/search/get?s=%s&type=1&limit=10&offset=0"
                  % urllib.parse.quote(kw), referer="https://music.163.com/")
    songs = ((d.get("result") or {}).get("songs")) or []
    pick = None
    for s in songs:
        if (s.get("name") or "").strip() != name:
            continue
        dur = (s.get("duration") or 0) / 1000.0
        if want_dur and abs(dur - want_dur) > 8:
            continue
        pick = s
        break
    if pick is None:
        return None, None, "无同名歌曲"
    ld = http_json("https://music.163.com/api/song/lyric?id=%s&lv=-1&kv=-1&tv=-1" % pick["id"],
                   referer="https://music.163.com/")
    lrc = ((ld.get("lrc") or {}).get("lyric")) or ""
    tlyric = ((ld.get("tlyric") or {}).get("lyric")) or ""  # 官方中文翻译（外语歌才有）
    if len(lrc) < 80:
        return None, None, "歌词为空"
    return lrc, tlyric, "网易云 id=%s" % pick["id"]


def _lrc_from_qq(name, artist, want_dur=None):
    kw = f"{name} {artist}".strip()
    d = http_json("https://c.y.qq.com/soso/fcgi-bin/client_search_cp?w=%s&format=json&n=10&p=1"
                  % urllib.parse.quote(kw), referer="https://y.qq.com/")
    lst = ((d.get("data") or {}).get("song") or {}).get("list") or []
    pick = None
    for s in lst:
        if (s.get("songname") or "").strip() != name:
            continue
        if want_dur and abs((s.get("interval") or 0) - want_dur) > 8:
            continue
        pick = s
        break
    if pick is None:
        return None, None, "无同名歌曲"
    ld = http_json("https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?songmid=%s"
                   "&format=json&nobase64=1&g_tk=5381" % pick["songmid"],
                   referer="https://y.qq.com/portal/player.html")
    lrc = ld.get("lyric") or ""
    trans = ld.get("trans") or ""  # QQ 音乐的翻译歌词
    if len(lrc) < 80:
        return None, None, "歌词为空"
    return lrc, trans, "QQ音乐 mid=%s" % pick["songmid"]


def _lrc_from_kugou(name, artist, want_dur=None):
    kw = f"{name} {artist}".strip()
    d = http_json("https://mobilecdn.kugou.com/api/v3/search/song?format=json&keyword=%s"
                  "&page=1&pagesize=10&showtype=1" % urllib.parse.quote(kw))
    items = (d.get("data") or {}).get("info") or []
    pick = None
    for it in items:
        if name not in (it.get("songname") or ""):
            continue
        if want_dur and abs((it.get("duration") or 0) - want_dur) > 8:
            continue
        pick = it
        break
    if pick is None:
        return None, None, "无匹配歌曲"
    ks = http_json("https://krcs.kugou.com/search?ver=1&man=yes&client=mobi&keyword=%s&duration=%s&hash=%s"
                   % (urllib.parse.quote(pick.get("songname") or name),
                      pick.get("duration") or "", pick.get("hash") or ""),
                   referer="https://m.kugou.com/")
    cds = (ks.get("data") or {}).get("candidates") or []
    if not cds:
        return None, None, "无歌词候选"
    c0 = cds[0]
    import base64
    dl = http_json("https://lyrics.kugou.com/download?ver=1&client=pc&id=%s&accesskey=%s&fmt=lrc&charset=utf8"
                   % (c0.get("id"), c0.get("accesskey")), referer="https://www.kugou.com/")
    content = base64.b64decode(dl.get("content") or "")
    lrc = content.decode("utf-8", "ignore")
    if len(lrc) < 80:
        return None, None, "歌词为空"
    return lrc, "", "酷狗 id=%s" % c0.get("id")


def _lrc_from_lrclib(name, artist, want_dur=None):
    kw = f"{name} {artist}".strip()
    results = http_json("https://lrclib.net/api/search?q=" + urllib.parse.quote(kw))
    best = None
    for r in results or []:
        if not r.get("syncedLyrics"):
            continue
        if want_dur and r.get("duration") and abs(r["duration"] - want_dur) > 8:
            continue
        score = 0
        if artist and artist.split("/")[0].lower() in (r.get("artistName") or "").lower():
            score += 2
        if name in (r.get("trackName") or ""):
            score += 1
        if best is None or score > best[0]:
            best = (score, r)
    if best is None:
        return None, None, "无同步歌词"
    return best[1]["syncedLyrics"], "", "lrclib id=%s" % best[1].get("id")


LYRIC_SOURCES = [
    ("网易云", _lrc_from_netease),
    ("QQ音乐", _lrc_from_qq),
    ("酷狗", _lrc_from_kugou),
    ("lrclib", _lrc_from_lrclib),
]


def fetch_lyrics(name, artist, want_dur=None, keep_credits=False, with_translation=True):
    """按顺序尝试各歌词源，返回 (lrc_text, 来源说明) 或 (None, 失败原因汇总)"""
    reasons = []
    for label, fn in LYRIC_SOURCES:
        try:
            lrc, tlyric, note = fn(name, artist, want_dur)
            if lrc:
                print(f"  [歌词] {label} 命中（{note}），{len(lrc)} 字符")
                if tlyric and with_translation:
                    merged = merge_bilingual(lrc, tlyric)
                    if merged:
                        lrc = merged
                        print(f"  [歌词] 已并入官方中文翻译（{len(tlyric)} 字符），外语歌会自动双语显示")
                if not keep_credits:
                    lrc = clean_lrc(lrc)
                return lrc, label
            reasons.append(f"{label}: {note}")
        except Exception as e:
            reasons.append(f"{label}: {type(e).__name__} {e}")
    return None, " / ".join(reasons)


def extract_embedded_cover(path):
    """从音频文件提取内嵌封面，成功返回图片字节，否则 None"""
    try:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".m4a":
            tags = MP4(path).tags
            covers = tags.get("covr") if tags else None
            if covers:
                return bytes(covers[0])
        elif ext == ".mp3":
            tags = ID3(path)
            pics = tags.getall("APIC") if tags else []
            if pics:
                return pics[0].data
        elif ext == ".flac":
            pics = FLAC(path).pictures
            if pics:
                return pics[0].data
    except Exception as e:
        print(f"  [封面] 内嵌封面提取失败：{e}")
    return None


def read_metadata(path):
    """读取歌名/歌手/时长，失败返回 (None, None, None)"""
    try:
        audio = mutagen.File(path, easy=True)
        if audio:
            title = (audio.get("title") or [None])[0]
            artist = (audio.get("artist") or [None])[0]
            dur = audio.info.length if audio.info else None
            return title, artist, dur
    except Exception:
        pass
    return None, None, None



def download(url, dest):
    data = http_get(url)
    with open(dest, "wb") as f:
        f.write(data)
    return len(data)


def append_to_playlist(name, artist, audio_url, cover_url, lrc_url):
    """把新歌追加到 musicConfig.ts 的 local.playlist（已存在同名歌曲则跳过）"""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = f.read()

    if f'url: "{audio_url}"' in config or f"url: '{audio_url}'" in config:
        print("  [歌单] 已存在相同音频路径，跳过歌单追加")
        return False

    entry = (
        "\t\t\t{\n"
        f"\t\t\t\tname: \"{name}\",\n"
        f"\t\t\t\tartist: \"{artist}\",\n"
        f"\t\t\t\turl: \"{audio_url}\",\n"
        f"\t\t\t\tcover: \"{cover_url}\",\n"
        f"\t\t\t\tlrc: \"{lrc_url}\",\n"
        "\t\t\t},\n"
    )
    m = re.search(r"(playlist:\s*\[\n)", config)
    if not m:
        print("  [歌单] !! 在 musicConfig.ts 里找不到 playlist 数组，请手动添加")
        return False
    config = config[:m.end()] + entry + config[m.end():]
    with open(CONFIG_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(config)
    print(f"  [歌单] 已追加到 musicConfig.ts：{name}")
    return True


MUSIC_MD_DIR = os.path.join(BLOG_ROOT, "src", "content", "bangumi", "music")


def write_music_md(name, artist, audio_url, cover_url, lrc_url):
    """生成 /music 可视化页面的收藏条目 md（已存在则跳过）"""
    os.makedirs(MUSIC_MD_DIR, exist_ok=True)
    md_path = os.path.join(MUSIC_MD_DIR, f"{name}.md")
    if os.path.exists(md_path):
        print("  [MD] 已存在，跳过")
        return
    import datetime
    today = datetime.date.today().isoformat()
    content = (
        "---\n"
        f"title: {name}\n"
        "category: music\n"
        "status: 3\n"
        "score: 0\n"
        f"image: {cover_url}\n"
        f"artist: {artist}\n"
        f"audioUrl: {audio_url}\n"
        f"lrcUrl: {lrc_url}\n"
        f"published: {today}\n"
        "---\n"
    )
    with open(md_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"  [MD] 已生成 src/content/bangumi/music/{name}.md（记得手动调 score/status）")


def process_local(path, server, dry=False, keep_credits=False, with_translation=True,
                  keep_lossless=False):
    """本地文件模式：提取内嵌封面 + 多源下载歌词 + 追加歌单"""
    base = os.path.splitext(os.path.basename(path))[0]
    meta_title, meta_artist, meta_dur = read_metadata(path)
    name = sanitize(meta_title or base)
    artist = (meta_artist or "").strip()
    print(f"\n处理：{os.path.basename(path)}  →  {name} / {artist or '(未知歌手)'}"
          + (f"  [{meta_dur:.0f}s]" if meta_dur else ""))

    cover_dest = os.path.join(COVER_DIR, f"{name}.jpg")
    lrc_dest = os.path.join(LRC_DIR, f"{name}.lrc")
    cover_url = f"/assets/music/cover/{name}.jpg"
    lrc_url = f"/assets/music/lrc/{name}.lrc"

    # 1. 封面：优先音频内嵌，没有就去网易云取专辑封面
    if os.path.exists(cover_dest):
        print("  [封面] 已存在，跳过")
    elif dry:
        print("  [封面] (dry-run) 跳过")
    else:
        img = extract_embedded_cover(path)
        note = "音频内嵌封面"
        if not img:
            try:
                img, note = fetch_cover(name, artist, meta_dur)
            except Exception as e:  # noqa: BLE001
                img, note = None, f"网易云取封面失败 {e}"
        if img:
            with open(cover_dest, "wb") as f:
                f.write(img)
            print(f"  [封面] 已保存（{note}）→ cover/{name}.jpg")
        else:
            print(f"  [封面] 没拿到（{note}）")
            print(f"         → 手动放一张图到 public/assets/music/cover/{name}.jpg 即可")

    # 2. 歌词：网易云 → QQ音乐 → 酷狗 → lrclib 依次兜底
    if os.path.exists(lrc_dest):
        print("  [歌词] 已存在，跳过（想重新抓就删掉该 .lrc 再跑一次）")
    elif dry:
        print("  [歌词] (dry-run) 跳过下载")
    else:
        lrc_text, note = fetch_lyrics(name, artist, want_dur=meta_dur, keep_credits=keep_credits,
                                      with_translation=with_translation)
        if lrc_text:
            with open(lrc_dest, "w", encoding="utf-8", newline="\n") as f:
                f.write(lrc_text)
            print(f"  [歌词] 已保存 → lrc/{name}.lrc（来源：{note}）")
        else:
            print(f"  [歌词] 全部源都没拿到：{note}")
            print("         → 可手动把 .lrc 丢进 public/assets/music/lrc/，再在 md 里写 lrcUrl")

    # 3. 音频：统一按「曲名.扩展名」落到 public/assets/music/，和封面/歌词/md 同名
    #    flac / wav 默认转成 MP3 320k（网页友好、体积只有 1/3，且能避开 Cloudflare 25MiB 单文件上限）
    if not dry:
        import shutil
        ext = os.path.splitext(path)[1].lower()
        src_abs = os.path.abspath(path)
        in_lib = os.path.dirname(src_abs) == os.path.abspath(MUSIC_DIR)
        lossless = ext in (".flac", ".wav")

        if lossless and not keep_lossless:
            dest_name = f"{name}.mp3"
        elif in_lib:
            dest_name = os.path.basename(path)   # 已经在音乐目录里，保持原名不动
        else:
            dest_name = f"{name}{ext}"
        audio_dest = os.path.join(MUSIC_DIR, dest_name)

        if os.path.exists(audio_dest) and src_abs != os.path.abspath(audio_dest):
            print(f"  [音频] {dest_name} 已存在，沿用（不覆盖）")
        elif src_abs != os.path.abspath(audio_dest):
            if lossless and not keep_lossless:
                ok, msg = convert_to_mp3(path, audio_dest)
                if ok:
                    print(f"  [音频] {msg} → {dest_name}"
                          f"（{os.path.getsize(path) / 1048576:.1f} → "
                          f"{os.path.getsize(audio_dest) / 1048576:.1f} MiB）")
                else:
                    dest_name = f"{name}{ext}"
                    audio_dest = os.path.join(MUSIC_DIR, dest_name)
                    shutil.copy2(path, audio_dest)
                    print(f"  [音频] {msg}；已直接复制为 {dest_name}")
                    print("         ⚠️ 无损文件超过 25 MiB 会导致 Cloudflare 部署失败")
            else:
                shutil.copy2(path, audio_dest)
                print(f"  [音频] 已复制为 {dest_name}（原文件保留不动）")

        if " " in dest_name:
            print("  [音频] !! 文件名里有空格，建议手工改成下划线")
        audio_url = f"/assets/music/{dest_name}"
        append_to_playlist(name, artist, audio_url, cover_url, lrc_url)
        write_music_md(name, artist, audio_url, cover_url, lrc_url)


def search_and_download(title, artist, server, out_dir, dry=False, keep_credits=False,
                        with_translation=True):
    """搜索下载模式：搜索 → 下载音频/封面/歌词 → 追加歌单"""
    query = f"{title} {artist}".strip()
    print(f"搜索: {query}")
    results = meting(server, "search", query)
    if not results:
        print("搜索无结果（Meting 公共源多数已失效），可用本地文件模式：")
        print('  python scripts/fetch-lrc.py "D:/Music/歌.mp3"')
        print("  或走 QQ/网易云直接抓：python scripts/fetch-lrc.py \"歌名\" \"歌手\" --lyrics-only")
        return
    for i, r in enumerate(results[:10], 1):
        print(f"  [{i:2}] {r.get('title', '?')} - {r.get('artist', '?')}")
    if dry:
        print("(dry-run) 只预览，不下载")
        return
    if sys.stdin.isatty():
        choice = input(f"选择序号 (1-{min(10, len(results))}, 默认 1): ").strip()
        idx = int(choice) if choice.isdigit() and 1 <= int(choice) <= min(10, len(results)) else 1
    else:
        idx = 1
    pick = results[idx - 1]
    name = sanitize(str(pick.get("title", "未知")))
    artist_name = str(pick.get("artist", ""))
    print(f"选中: {name} - {artist_name}")

    cover_dest = os.path.join(COVER_DIR, f"{name}.jpg")
    lrc_dest = os.path.join(LRC_DIR, f"{name}.lrc")
    audio_dest = os.path.join(MUSIC_DIR, f"{name}.m4a")

    for label, url, dest in [
        ("音频", pick.get("url"), audio_dest),
        ("封面", pick.get("pic"), cover_dest),
    ]:
        if not url:
            print(f"  [{label}] API 未提供链接，跳过")
            continue
        try:
            size = download(url, dest)
            print(f"  [{label}] {size / 1024 / 1024:.1f} MB" if label == "音频" and size > 1e6
                  else f"  [{label}] {size} 字节 → {os.path.relpath(dest, BLOG_ROOT)}")
        except Exception as e:
            print(f"  [{label}] 下载失败：{e}")

    # 歌词统一走多源兜底（Meting 返回的 lrc 链接多为失效死链）
    if not os.path.exists(lrc_dest):
        lrc_text, note = fetch_lyrics(name, artist_name, keep_credits=keep_credits,
                                      with_translation=with_translation)
        if lrc_text:
            with open(lrc_dest, "w", encoding="utf-8", newline="\n") as f:
                f.write(lrc_text)
            print(f"  [歌词] 已保存 → lrc/{name}.lrc（来源：{note}）")
        else:
            print(f"  [歌词] 全部源都没拿到：{note}")

    audio_url = f"/assets/music/{urllib.parse.quote(os.path.basename(audio_dest))}" if os.path.exists(audio_dest) else ""
    cover_url = f"/assets/music/cover/{name}.jpg" if os.path.exists(cover_dest) else ""
    lrc_url = f"/assets/music/lrc/{name}.lrc" if os.path.exists(lrc_dest) else ""
    if audio_url:
        append_to_playlist(name, artist_name, audio_url, cover_url, lrc_url)
        write_music_md(name, artist_name, audio_url, cover_url, lrc_url)


def lyrics_only(title, artist, keep_credits=False, dry=False, with_translation=True):
    """只抓歌词：不下载音频，直接把 .lrc 落到 public/assets/music/lrc/"""
    name = sanitize(title)
    lrc_dest = os.path.join(LRC_DIR, f"{name}.lrc")
    print(f"\n只抓歌词：{name} / {artist or '(未知歌手)'}")
    if os.path.exists(lrc_dest):
        print("  [歌词] 已存在，跳过（想重新抓就删掉该 .lrc 再跑一次）")
        return
    lrc_text, note = fetch_lyrics(name, artist, keep_credits=keep_credits,
                                  with_translation=with_translation)
    if not lrc_text:
        print(f"  [歌词] 全部源都没拿到：{note}")
        return
    if dry:
        print("(dry-run) 不写文件，预览前 5 行：")
        print("\n".join(lrc_text.splitlines()[:5]))
        return
    with open(lrc_dest, "w", encoding="utf-8", newline="\n") as f:
        f.write(lrc_text)
    print(f"  [歌词] 已保存 → public/assets/music/lrc/{name}.lrc（来源：{note}）")
    print(f"         在 src/content/bangumi/music/{name}.md 里加一行：")
    print(f"           lrcUrl: /assets/music/lrc/{name}.lrc")


def main():
    os.makedirs(COVER_DIR, exist_ok=True)
    os.makedirs(LRC_DIR, exist_ok=True)

    ap = argparse.ArgumentParser(description="音乐歌词/封面一键提取（Firefly 博客专用）")
    ap.add_argument("source", help="本地音频文件/目录，或搜索模式下的歌名")
    ap.add_argument("artist", nargs="?", default="", help="歌手名（可选，能显著提高匹配准确度）")
    ap.add_argument("--server", default="netease", help="搜索模式的 Meting 平台：netease/tencent/kugou")
    ap.add_argument("--lyrics-only", action="store_true", help="只抓歌词（不下载音频）")
    ap.add_argument("--keep-credits", action="store_true", help="保留开头那段制作人员名单")
    ap.add_argument("--no-translation", action="store_true", help="不并入中文翻译（默认外语歌自动双语）")
    ap.add_argument("--keep-lossless", action="store_true",
                    help="flac/wav 不转 MP3，原样放进音乐目录（注意 25MiB 上限）")
    ap.add_argument("--no-proxy", action="store_true", help="强制直连，不走系统代理")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不下载不写配置")
    args = ap.parse_args()

    global _PROXY_OFF
    _PROXY_OFF = args.no_proxy

    src = args.source
    if args.lyrics_only:
        lyrics_only(src, args.artist, args.keep_credits, args.dry_run, not args.no_translation)
    elif os.path.isdir(src):
        files = [os.path.join(src, f) for f in sorted(os.listdir(src)) if f.lower().endswith(AUDIO_EXTS)]
        if not files:
            print(f"目录里没有音频文件：{src}")
            return
        print(f"共 {len(files)} 个音频文件")
        for f in files:
            process_local(f, args.server, args.dry_run, args.keep_credits, not args.no_translation,
                          args.keep_lossless)
    elif os.path.isfile(src):
        process_local(src, args.server, args.dry_run, args.keep_credits, not args.no_translation,
                      args.keep_lossless)
    else:
        # 当作歌名，进入搜索下载模式
        search_and_download(src, args.artist, args.server, out_dir=MUSIC_DIR,
                            dry=args.dry_run, keep_credits=args.keep_credits,
                            with_translation=not args.no_translation)


if __name__ == "__main__":
    main()
