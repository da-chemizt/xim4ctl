#!/usr/bin/env python3
"""Download the current XIM4 game-support database (.ximmr) from the vendor's own server and
verify its checksum.

The .ximmr holds the per-game aim "Smart Translator" blobs (needed to give an authored config the
correct per-game aim feel) plus game metadata. It is the vendor's copyrighted data and is NOT
distributed with this project — this fetches your own copy from the source.

How it works: the manifest at .../Manager/VersionXR names the current .ximmr URL (line 1) and its
MD5 (line 2). We fetch line 1 and verify against line 2.

Usage: python3 fetch_gamedb.py [output-dir]
"""
import sys, os, hashlib, urllib.request

MANIFEST = "https://cloud.xim.tech/Manager/VersionXR"

def _get(url):
    # the server is behind a CDN that blocks the default Python user-agent
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()

def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "."
    lines = _get(MANIFEST).decode("latin1").splitlines()
    blob_url = lines[0].strip().replace("http://", "https://")   # the server redirects to https
    md5_expected = lines[1].strip().lower()
    name = blob_url.rsplit("/", 1)[-1]
    print("database:     %s" % name)
    print("expected md5: %s" % md5_expected)
    print("downloading   %s ..." % blob_url)
    data = _get(blob_url)
    md5 = hashlib.md5(data).hexdigest()
    if md5 != md5_expected:
        print("MD5 MISMATCH (got %s) — not saving" % md5)
        sys.exit(1)
    path = os.path.join(outdir, name)
    with open(path, "wb") as f:
        f.write(data)
    print("OK  %d bytes, md5 %s  ->  %s" % (len(data), md5, path))

if __name__ == "__main__":
    main()
