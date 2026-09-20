#!/usr/bin/env python3
import argparse
import base64
import json
import re
import sys
import time
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

API = "https://api.cdnlivetv.is/api/v1/channels/"
PLAYER = "https://cdnlivetv.tv/api/v1/channels/player/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
REFERER = "https://cdnlivetv.is/"

ENGLISH_CODES = ("us", "gb", "ca", "au", "nz")


def http_get(url, referer=REFERER, tries=5):
    headers = {
        "User-Agent": UA,
        "Referer": referer,
        "Accept": "*/*",
    }
    for attempt in range(tries):
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as e:
            code = getattr(e, "code", None)
            if code == 429:
                wait = min(60, (attempt + 1) * 5)
                print(f"  rate limited, sleeping {wait}s ...", file=sys.stderr)
                time.sleep(wait)
                continue
            if attempt == tries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}")


def b64dec(s):
    s = s + "=" * ((4 - len(s) % 4) % 4)
    return base64.b64decode(s).decode("utf-8", "replace")


def extract_stream_url(html):
    ch = re.search(r'var\s+_CH\s*=\s*"([0-9a-f]+)"', html)
    if not ch:
        return None
    chunks = re.findall(r"var\s+\w+\s*=\s*'([A-Za-z0-9+/=]+)'\s*;", html)
    full = "".join(b64dec(c) for c in chunks)
    m = re.search(
        r"https?://[^\"'`\s]+?/playlist\.m3u8\?token=[A-Za-z0-9+/=]+"
        r"|\?token=[A-Za-z0-9+/=]+",
        full,
    )
    if not m:
        return None
    url = m.group(0)
    if url.startswith("?"):
        url = f"https://cdnlivetv.tv/secure/api/v1/{ch.group(1)}/playlist.m3u8" + url
    return url


def build_playlist(limit=None, codes=ENGLISH_CODES, delay=0.0):
    params = {"user": "cdnlivetv", "plan": "free"}
    url = API + "?" + urlencode(params)
    print("Fetching channel list ...", file=sys.stderr)
    data = json.loads(http_get(url))
    channels = [c for c in data.get("channels", []) if c.get("code") in codes]
    print(f"Total: {data.get('total_channels')}, English: {len(channels)}",
          file=sys.stderr)

    channels = channels if limit is None else channels[:limit]
    entries = []
    failed = 0
    for i, ch in enumerate(channels, 1):
        name = ch["name"]
        q = urlencode({
            "name": name, "code": ch["code"],
            "user": "cdnlivetv", "plan": "free",
        })
        stream = None
        tries = 3
        while tries > 0:
            try:
                html = http_get(PLAYER + "?" + q)
                stream = extract_stream_url(html)
                break
            except Exception as e:
                tries -= 1
                print(f"  error {name}: {e}", file=sys.stderr)
                time.sleep(3)
        if stream:
            entries.append((ch, stream))
        else:
            failed += 1
            print(f"  skipped: {name} (no stream url)", file=sys.stderr)
        print(f"  [{i}/{len(channels)}] {name}", file=sys.stderr)
        if delay:
            time.sleep(delay)

    return entries, failed


def write_m3u(entries, out):
    with open(out, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ch, stream in entries:
            esc = lambda s: re.sub(r"[\s,]", "_", s)
            f.write(
                f'#EXTINF:-1 tvg-id="{esc(ch["name"])}" '
                f'tvg-logo="{ch.get("image", "")}" '
                f'group-title="{esc(ch["code"].upper())} TV",{ch["name"]}\n'
            )
            f.write(stream + "\n")


def main():
    ap = argparse.ArgumentParser(
        description="Generate an m3u playlist of English channels from CDN Live TV.")
    ap.add_argument("-o", "--output", default="cdnlivetv_english.m3u8",
                    help="output playlist file")
    ap.add_argument("--codes", default=",".join(ENGLISH_CODES),
                    help="comma-separated country codes to include")
    ap.add_argument("--limit", type=int, default=None,
                    help="only process first N channels (for testing)")
    ap.add_argument("--delay", type=float, default=0.7,
                    help="seconds to wait between player page requests")
    args = ap.parse_args()

    codes = tuple(c.strip().lower() for c in args.codes.split(",") if c.strip())
    entries, failed = build_playlist(limit=args.limit, codes=codes,
                                     delay=args.delay)
    write_m3u(entries, args.output)
    print(f"Wrote {len(entries)} channels to {args.output} "
          f"({failed} failed)", file=sys.stderr)


if __name__ == "__main__":
    main()