#!/usr/bin/env python
"""重排 /music/ 歌单顺序并把两边（内容集合 + musicConfig）同步好。

背景：/music/ 页按 src/content/bangumi/music/*.md 的 published 倒序排，
同一天的顺序不稳定，而且侧边栏播放器读的是 musicConfig.ts 的 local.playlist，
两处顺序容易不一致。这个脚本负责统一。

做的事：
  1. 读所有音乐 md，按 published 倒序（同日期按文件名稳定排序）确定歌曲顺序
  2. 重新编号 published：最新一首保持原日期，之后每首递减 1 天（保证顺序稳定）
  3. 按同一顺序重写 musicConfig.ts 的 local.playlist（保留 artist/封面/歌词）

想让某首歌靠前：把它的 published 改成一个更大的日期，再跑本脚本。

用法：
  python scripts/music-order.py            # 直接写入
  python scripts/music-order.py --dry-run  # 只打印将得到的结果
"""

import argparse
import datetime
import os
import re
import sys

BLOG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSIC_MD_DIR = os.path.join(BLOG_ROOT, "src", "content", "bangumi", "music")
CONFIG_PATH = os.path.join(BLOG_ROOT, "src", "config", "musicConfig.ts")

FIELDS = ("title", "artist", "image", "audioUrl", "lrcUrl", "published")


def read_md(path):
    """读 frontmatter 里的几个字段"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", text, re.S)
    if not m:
        return None
    data = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()
    if data.get("category") and data["category"] != "music":
        return None
    data["_path"] = path
    data["_text"] = text
    data["_fm_end"] = m.end(1)
    data["_fm_block"] = m.group(1)
    return data


def rewrite_published(data, new_date):
    if data.get("published") == new_date:
        return False
    block = data["_fm_block"]
    if re.search(r"^published:", block, re.M):
        new_block = re.sub(r"^published:.*$", f"published: {new_date}", block, count=1, flags=re.M)
    else:
        new_block = block + f"\npublished: {new_date}"
    new_text = data["_text"][: data["_fm_end"] - len(block)] + new_block + data["_text"][data["_fm_end"]:]
    with open(data["_path"], "w", encoding="utf-8", newline="\n") as f:
        f.write(new_text)
    return True


def build_playlist_ts(songs):
    lines = ["\t\tplaylist: ["]
    for s in songs:
        lines.append("\t\t\t{")
        lines.append(f'\t\t\t\tname: "{s["title"]}",')
        lines.append(f'\t\t\t\tartist: "{s.get("artist", "")}",')
        lines.append(f'\t\t\t\turl: "{s.get("audioUrl", "")}",')
        lines.append(f'\t\t\t\tcover: "{s.get("image", "")}",')
        lines.append(f'\t\t\t\tlrc: "{s.get("lrcUrl", "")}",')
        lines.append("\t\t\t},")
    lines.append("\t\t]")
    return "\n".join(lines)


def replace_playlist_block(text, new_block):
    """替换 local: { playlist: [ ... ], } 里的 playlist 数组（按括号配对找结尾）"""
    anchor = text.find("playlist: [")
    if anchor < 0:
        raise SystemExit("musicConfig.ts 里找不到 playlist: [")
    start = text.rindex("\n", 0, anchor) + 1
    i = text.index("[", anchor)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "[":
            depth += 1
        elif text[j] == "]":
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    else:
        raise SystemExit("playlist 数组括号不配对")
    if not text[end:].lstrip().startswith(","):
        raise SystemExit("playlist 数组后面不是逗号，结构异常，已放弃")
    # 新块不带尾逗号，原来的尾逗号保留在 text[end:] 里，避免出现 `],,`
    return text[:start] + new_block + text[end:]


def main():
    ap = argparse.ArgumentParser(description="重排音乐页歌单顺序")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    args = ap.parse_args()

    files = [f for f in sorted(os.listdir(MUSIC_MD_DIR)) if f.endswith(".md")]
    songs = []
    for f in files:
        d = read_md(os.path.join(MUSIC_MD_DIR, f))
        if d and d.get("audioUrl"):
            songs.append(d)
    if not songs:
        print("没有找到带 audioUrl 的音乐 md")
        return

    def pub(s):
        try:
            return datetime.date.fromisoformat(s.get("published", "1970-01-01"))
        except ValueError:
            return datetime.date(1970, 1, 1)

    songs.sort(key=lambda s: (pub(s), s["title"]), reverse=True)
    newest = pub(songs[0])

    print(f"共 {len(songs)} 首，顺序：")
    changed = 0
    for idx, s in enumerate(songs):
        new_date = (newest - datetime.timedelta(days=idx)).isoformat()
        flag = ""
        if s.get("published") != new_date:
            flag = f"  (published {s.get('published')} → {new_date})"
            changed += 1
        print(f"  {idx + 1}. {s['title']}{flag}")
        s["_new_date"] = new_date

    if args.dry_run:
        print("\n(dry-run) 未写入")
        return

    for s in songs:
        rewrite_published(s, s["_new_date"])

    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = f.read()
    cfg_new = replace_playlist_block(cfg, build_playlist_ts(songs))
    with open(CONFIG_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(cfg_new)

    print(f"\n已更新 {changed} 个 published，并重写 musicConfig.ts 的 local.playlist")


if __name__ == "__main__":
    main()
