"""Fetch point-in-time exposure inputs for the F-2 exposure analysis (exploratory).

Stages (both resumable; every raw response is cached under verification/exposure/cache/):
  downloads : npm daily download counts per package for the 365-day window ending at each origin
              (https://api.npmjs.org/downloads/range/{start}:{end}/{pkg[,pkg...]}).
              Unscoped packages are queried in bulk (<=128 per request, bulk range <=365 days);
              scoped packages one at a time.  Daily ranges (not point totals) are kept so that
              zero-filled history gaps in the npm API can be detected (see README).
  ghsa      : GitHub reviewed npm advisories published up to 2020-12-31.  The project cache
              (cache/ghsa/advisories.json) only covers published 2021-01-01..2024-12-31, which
              would left-truncate prior-advisory counts.

Usage: python fetch_exposure.py downloads|ghsa|all
"""
from pathlib import Path
from datetime import date, timedelta
import hashlib, json, sys, time, urllib.parse, urllib.request, urllib.error

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CACHE = HERE / 'cache'
ORIGINS = ['2020-12-31', '2021-12-31', '2022-12-31', '2023-12-31']
import socket
_gai = socket.getaddrinfo


def _ipv4_only(host, *args, **kwargs):
    # IPv6 connects to api.npmjs.org hang on this machine (getaddrinfo lists 12 IPv6 addresses first)
    res = _gai(host, *args, **kwargs)
    v4 = [r for r in res if r[0] == socket.AF_INET]
    return v4 or res


socket.getaddrinfo = _ipv4_only
UA = {'User-Agent': 'thesis-exposure-analysis/1.0 (academic research; low rate)', 'Accept': 'application/json'}
DELAY = 0.4


def window(origin):
    end = date.fromisoformat(origin)
    return (end - timedelta(days=364)).isoformat(), origin  # 365 days inclusive


def cache_file(origin, package):
    safe = urllib.parse.quote(package, safe='')
    return CACHE / 'npm_downloads' / origin / f"{safe}_{hashlib.sha1(package.encode()).hexdigest()[:8]}.json"


def get(url, allow_404=False):
    for attempt in range(8):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read().decode('utf-8')), dict(r.headers)
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'replace')
            if e.code == 404 and allow_404:
                try:
                    return 404, json.loads(body), dict(e.headers)
                except Exception:
                    return 404, {'error': body}, dict(e.headers)
            if e.code in (429, 500, 502, 503, 504):
                wait = min(120, 2 ** attempt * 2)
                print('HTTP', e.code, 'retry in', wait, url[:120], flush=True)
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            wait = min(120, 2 ** attempt * 2)
            print('net error', e, 'retry in', wait, flush=True)
            time.sleep(wait)
    raise RuntimeError('failed after retries: ' + url)


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def packages():
    import pandas as pd
    return sorted(pd.read_parquet(ROOT / 'data/processed/paired.parquet', columns=['package']).package.unique())


def fetch_downloads():
    pkgs = packages()
    requests = 0
    for origin in ORIGINS:
        start, end = window(origin)
        todo = [p for p in pkgs if not cache_file(origin, p).exists()]
        print(origin, start, end, 'to fetch', len(todo), flush=True)
        unscoped = [p for p in todo if not p.startswith('@')]
        scoped = [p for p in todo if p.startswith('@')]
        for i in range(0, len(unscoped), 128):
            chunk = unscoped[i:i + 128]
            if len(chunk) == 1:
                scoped.append(chunk[0]); continue
            url = f"https://api.npmjs.org/downloads/range/{start}:{end}/" + ','.join(urllib.parse.quote(p, safe='') for p in chunk)
            status, body, _ = get(url, allow_404=True)
            requests += 1
            if status == 404 or not isinstance(body, dict) or 'error' in body:
                # whole bulk failed: fall back to single queries for this chunk
                print('bulk failed, falling back to single', body if not isinstance(body, dict) else body.get('error'), flush=True)
                scoped.extend(chunk); continue
            for p in chunk:
                if p in body:
                    obj = body[p]
                    save(cache_file(origin, p), {'package': p, 'origin': origin, 'mode': 'bulk', 'status': 200 if obj else 'null_in_bulk', 'response': obj})
                else:
                    scoped.append(p)  # name normalisation mismatch -> query alone
            time.sleep(DELAY)
            print(origin, 'bulk', i + len(chunk), '/', len(unscoped), flush=True)
        for j, p in enumerate(scoped):
            url = f"https://api.npmjs.org/downloads/range/{start}:{end}/" + urllib.parse.quote(p, safe='@')
            status, body, _ = get(url, allow_404=True)
            requests += 1
            save(cache_file(origin, p), {'package': p, 'origin': origin, 'mode': 'single', 'status': status, 'response': body})
            time.sleep(DELAY)
            if j % 50 == 0:
                print(origin, 'single', j, '/', len(scoped), flush=True)
    print('downloads done; requests', requests, flush=True)


def fetch_ghsa():
    out = CACHE / 'ghsa_pre2021'
    done = out / 'complete.json'
    if done.exists():
        print('ghsa cache complete'); return
    url = 'https://api.github.com/advisories?' + urllib.parse.urlencode({'ecosystem': 'npm', 'type': 'reviewed', 'published': '1990-01-01..2020-12-31', 'per_page': 100, 'sort': 'published', 'direction': 'asc'})
    first = url
    pages = []
    n = 0
    while url:
        n += 1
        status, body, headers = get(url)
        f = out / f'page-{n}.json'
        save(f, body)
        pages.append({'file': f.name, 'url': url, 'count': len(body), 'sha256': hashlib.sha256(f.read_bytes()).hexdigest()})
        link = headers.get('Link') or headers.get('link') or ''
        url = None
        for part in link.split(','):
            if 'rel="next"' in part:
                url = part[part.index('<') + 1:part.index('>')]
        print('ghsa page', n, len(body), 'remaining', headers.get('X-RateLimit-Remaining'), flush=True)
        time.sleep(1.5)
    allrows = [a for p in pages for a in json.loads((out / p['file']).read_text(encoding='utf-8'))]
    save(out / 'advisories.json', allrows)
    save(done, {'complete': True, 'query': first, 'pages': pages, 'advisories': len(allrows), 'completed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
    print('ghsa done', len(allrows), flush=True)


if __name__ == '__main__':
    stage = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if stage in ('ghsa', 'all'):
        fetch_ghsa()
    if stage in ('downloads', 'all'):
        fetch_downloads()
