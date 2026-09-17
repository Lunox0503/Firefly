#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fetch-lrc.py — 音乐工具脚本（Firefly 博客专用，参考 tsh520 博客教程思路改写）

功能：
  1. 本地文件模式：读取 m4a/mp3/flac 的内嵌封面 → 多源搜索下载同步歌词(.lrc)
     → 自动追加到 src/config/musicConfig.ts 的 local.playlist + 写 bangumi md
  2. 搜索下载模式：按歌名(+歌手)搜索 → 下载音频/封面/歌词 → 追加歌单

歌词来源（按顺序兜底，任一命中即停）：
  网易云 → QQ音乐 → 酷狗 → lrclib.net
  （公共 Meting API 大多已失效，故不再作为主源）

输出目录：
  public/assets/music/          音频（搜索模式下载到这里；本地模式不移动原文件）
  public/assets/music/cover/    封面 .jpg
  public/assets/music/lrc/      同步歌词 .lrc

用法：
  python fetch-lrc.py "D:/Music/歌.m4a"            # 单个本地文件
  python fetch-lrc.py "D:/Music/"                  # 批量处理整个目录
  python fetch-lrc.py "晴天" "周杰伦"              # 搜索下载模式
  python fetch-lrc.py "晴天" --dry-run             # 只搜索预览，不下载
  python fetch-lrc.py "歌.m4a" --keep-credits      # 保留开头制作人员名单
  python fetch-lrc.py "歌.m4a" --no-proxy          # 强制直连（默认走系统代理）

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


def clean_lrc(text):
    """清掉开头那段挤在几秒内滚完的制作人员名单，只留正片歌词"""
    out, seen_lyric = [], False
    for line in text.splitlines():
        if not line.strip():
            continue
        if META_RE.match(line):
            out.append(line)
            continue
        if not re.match(r"^\[\d{1,2}:\d{1,2}([.:]\d{1,3})?\]", line):
            continue
        body = re.sub(r"^(\[\d{1,2}:\d{1,2}([.:]\d{1,3})?\])+", "", line).strip()
        if not body:
            continue
        if not seen_lyric and CREDIT_RE.search(body):
            continue
        seen_lyric = True
        out.append(line)
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
        return None, "无同名歌曲"
    ld = http_json("https://music.163.com/api/song/lyric?id=%s&lv=1&kv=1&tv=-1" % pick["id"],
                   referer="https://music.163.com/")
    lrc = ((ld.get("lrc") or {}).get("lyric")) or ""
    if len(lrc) < 80:
        return None, "歌词为空"
    return lrc, "网易云 id=%s" % pick["id"]


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
        return None, "无同名歌曲"
    ld = http_json("https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?songmid=%s"
                   "&format=json&nobase64=1&g_tk=5381" % pick["songmid"],
                   referer="https://y.qq.com/portal/player.html")
    lrc = ld.get("lyric") or ""
    if len(lrc) < 80:
        return None, "歌词为空"
    return lrc, "QQ音乐 mid=%s" % pick["songmid"]


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
        return None, "无匹配歌曲"
    ks = http_json("https://krcs.kugou.com/search?ver=1&man=yes&client=mobi&keyword=%s&duration=%s&hash=%s"
                   % (urllib.parse.quote(pick.get("songname") or name),
                      pick.get("duration") or "", pick.get("hash") or ""),
                   referer="https://m.kugou.com/")
    cds = (ks.get("data") or {}).get("candidates") or []
    if not cds:
        return None, "无歌词候选"
    c0 = cds[0]
    import base64
    dl = http_json("https://lyrics.kugou.com/download?ver=1&client=pc&id=%s&accesskey=%s&fmt=lrc&charset=utf8"
                   % (c0.get("id"), c0.get("accesskey")), referer="https://www.kugou.com/")
    content = base64.b64decode(dl.get("content") or "")
    lrc = content.decode("utf-8", "ignore")
    if len(lrc) < 80:
        return None, "歌词为空"
    return lrc, "酷狗 id=%s" % c0.get("id")


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
        return None, "无同步歌词"
    return best[1]["syncedLyrics"], "lrclib id=%s" % best[1].get("id")


LYRIC_SOURCES = [
    ("网易云", _lrc_from_netease),
    ("QQ音乐", _lrc_from_qq),
    ("酷狗", _lrc_from_kugou),
    ("lrclib", _lrc_from_lrclib),
]


def fetch_lyrics(name, artist, want_dur=None, keep_credits=False):
    """按顺序尝试各歌词源，返回 (lrc_text, 来源说明) 或 (None, 失败原因汇总)"""
    reasons = []
    for label, fn in LYRIC_SOURCES:
        try:
            lrc, note = fn(name, artist, want_dur)
            if lrc:
                print(f"  [歌词] {label} 命中（{note}），{len(lrc)} 字符")
                return (lrc if keep_credits else clean_lrc(lrc)), label
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
        "status: 2\n"
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


def process_local(path, server, dry=False, keep_credits=False):
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

    # 1. 封面：优先内嵌
    if os.path.exists(cover_dest):
        print("  [封面] 已存在，跳过")
    else:
        img = extract_embedded_cover(path)
        if img and not dry:
            with open(cover_dest, "wb") as f:
                f.write(img)
            print(f"  [封面] 从文件内嵌提取 → {os.path.relpath(cover_dest, BLOG_ROOT)}")
        else:
            print("  [封面] 无内嵌封面，稍后由搜索结果补")

    # 2. 歌词：网易云 → QQ音乐 → 酷狗 → lrclib 依次兜底
    if os.path.exists(lrc_dest):
        print("  [歌词] 已存在，跳过（想重新抓就删掉该 .lrc 再跑一次）")
    elif dry:
        print("  [歌词] (dry-run) 跳过下载")
    else:
        lrc_text, note = fetch_lyrics(name, artist, want_dur=meta_dur, keep_credits=keep_credits)
        if lrc_text:
            with open(lrc_dest, "w", encoding="utf-8", newline="\n") as f:
                f.write(lrc_text)
            print(f"  [歌词] 已保存 → lrc/{name}.lrc（来源：{note}）")
        else:
            print(f"  [歌词] 全部源都没拿到：{note}")
            print("         → 可手动把 .lrc 丢进 public/assets/music/lrc/，再在 md 里写 lrcUrl")

    # 3. 歌单追加（本地模式音频路径直接指向 public/assets/music/ 下的原文件）
    audio_name = sanitize(os.path.splitext(os.path.basename(path))[0])
    audio_dest = os.path.join(MUSIC_DIR, os.path.basename(path))
    if not dry:
        if os.path.abspath(path) != os.path.abspath(audio_dest) and not os.path.exists(audio_dest):
            import shutil
            shutil.copy2(path, audio_dest)
            print(f"  [音频] 已复制到 public/assets/music/（原文件保留不动）")
        audio_url = f"/assets/music/{urllib.parse.quote(os.path.basename(audio_dest))}"
        append_to_playlist(name, artist, audio_url, cover_url, lrc_url)
        write_music_md(name, artist, audio_url, cover_url, lrc_url)


def search_and_download(title, artist, server, out_dir, dry=False, keep_credits=False):
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
        lrc_text, note = fetch_lyrics(name, artist_name, keep_credits=keep_credits)
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


def lyrics_only(title, artist, keep_credits=False, dry=False):
    """只抓歌词：不下载音频，直接把 .lrc 落到 public/assets/music/lrc/"""
    name = sanitize(title)
    lrc_dest = os.path.join(LRC_DIR, f"{name}.lrc")
    print(f"\n只抓歌词：{name} / {artist or '(未知歌手)'}")
    if os.path.exists(lrc_dest):
        print("  [歌词] 已存在，跳过（想重新抓就删掉该 .lrc 再跑一次）")
        return
    lrc_text, note = fetch_lyrics(name, artist, keep_credits=keep_credits)
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
    ap.add_argument("--no-proxy", action="store_true", help="强制直连，不走系统代理")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不下载不写配置")
    args = ap.parse_args()

    global _PROXY_OFF
    _PROXY_OFF = args.no_proxy

    src = args.source
    if args.lyrics_only:
        lyrics_only(src, args.artist, args.keep_credits, args.dry_run)
    elif os.path.isdir(src):
        files = [os.path.join(src, f) for f in sorted(os.listdir(src)) if f.lower().endswith(AUDIO_EXTS)]
        if not files:
            print(f"目录里没有音频文件：{src}")
            return
        print(f"共 {len(files)} 个音频文件")
        for f in files:
            process_local(f, args.server, args.dry_run, args.keep_credits)
    elif os.path.isfile(src):
        process_local(src, args.server, args.dry_run, args.keep_credits)
    else:
        # 当作歌名，进入搜索下载模式
        search_and_download(src, args.artist, args.server, out_dir=MUSIC_DIR,
                            dry=args.dry_run, keep_credits=args.keep_credits)


if __name__ == "__main__":
    main()
