"""Fetch pinned, read-only upstream evidence; never execute upstream code."""
import argparse
import concurrent.futures
import datetime as dt
import json
from pathlib import Path
import re
import sys
import urllib.request

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from career_ops.config import configured_path

REGISTRY = configured_path('oss_registry', 'examples/oss-registry.json')
OUT = configured_path('oss_reference', 'private/oss-reference')

def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'career-ops-source-review/0.1'})
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read()

def metadata(record):
    # Reviewed evidence stays pinned. A routine rerun is a retry of this snapshot,
    # not authorization to replace it with a moving default-branch HEAD.
    if record.get('commit'):
        if not re.fullmatch(r'[0-9a-fA-F]{40}', str(record['commit'])):
            return {**record, 'error': 'Pinned commit must be a full 40-character Git SHA; no HEAD fallback'}
        return dict(record)
    repo = record['url'].removeprefix('https://github.com/')
    try:
        data = json.loads(fetch('https://api.github.com/repos/' + repo))
        commit = json.loads(fetch('https://api.github.com/repos/' + repo + '/commits/' + data['default_branch']))
        return {**record, 'repository': repo, 'license': (data.get('license') or {}).get('spdx_id', 'unknown'),
                'commit': commit['sha'], 'default_branch': data['default_branch'], 'pushed_at': data['pushed_at'],
                'commit_date': commit['commit']['committer']['date'], 'archived': data['archived'],
                'stars_observed': data['stargazers_count'], 'description': data.get('description'), 'error': None}
    except Exception as exc:
        return {**record, 'repository': repo, 'error': str(exc)}

def snapshot(record):
    if record.get('error'):
        return record
    target = OUT / record['repository'].replace('/', '__')
    target.mkdir(parents=True, exist_ok=True)
    try:
        tree = json.loads(fetch(f"https://api.github.com/repos/{record['repository']}/git/trees/{record['commit']}?recursive=1"))
        (target / 'tree.json').write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding='utf-8')
        files = [x['path'] for x in tree.get('tree', []) if x['type'] == 'blob']
        selected = [f for f in files if '/' not in f and (f.lower().startswith('readme') or f.lower().startswith('license'))]
        record['reference_files'] = selected
        for filename in selected:
            content = fetch(f"https://raw.githubusercontent.com/{record['repository']}/{record['commit']}/{filename}")
            (target / filename).write_bytes(content)
        (target / 'provenance.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as exc:
        record['snapshot_error'] = str(exc)
    return record

def main():
    global REGISTRY, OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', type=Path, default=REGISTRY)
    parser.add_argument('--output-dir', type=Path, default=OUT)
    args = parser.parse_args()
    REGISTRY, OUT = args.registry.resolve(), args.output_dir.resolve()
    if not REGISTRY.is_file():
        parser.error('登记文件不存在；请指定 --registry，或使用 examples/oss-registry.json')
    registry = json.loads(REGISTRY.read_text(encoding='utf-8'))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        registry['repositories'] = list(pool.map(metadata, registry['repositories']))
    registry['retrieved_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    OUT.mkdir(parents=True, exist_ok=True)
    result_registry = OUT / 'registry.json'
    result_registry.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        registry['repositories'] = list(pool.map(snapshot, registry['repositories']))
    result_registry.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for record in registry['repositories']:
        print(json.dumps({k: record.get(k) for k in ('repository', 'license', 'commit', 'pushed_at', 'error', 'snapshot_error')}, ensure_ascii=False))

if __name__ == '__main__':
    main()
