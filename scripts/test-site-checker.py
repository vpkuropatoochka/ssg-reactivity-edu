"""Exercise checker failures on disposable copies; never mutate the real build."""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'evidence/02-reactivity/checker'
BUILD = ROOT / 'build'
CHECKER = ROOT / 'scripts/check-site.py'

def snapshot(directory):
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and '.lektor' not in p.relative_to(directory).parts}

def append_html(site, markup, relative='index.html'):
    file = site / relative
    file.write_text(file.read_text().replace('</body>', markup + '\n</body>'))

def css(site, value):
    file = site / 'static/style.css'
    file.write_text(file.read_text() + '\n' + value + '\n')

def good_examples(site):
    (site / 'данные one.txt').write_text('Real file for encoded-URL check.')
    append_html(site, '<h2 id="раздел">Раздел</h2><a name="legacy-anchor"></a>', 'about/index.html')
    append_html(site, '<a href="about/?source=test#%D1%80%D0%B0%D0%B7%D0%B4%D0%B5%D0%BB">Якорь с query</a><a href="about/#legacy-anchor">Старый якорь</a><a href="about/#top">Начало</a><a href="%D0%B4%D0%B0%D0%BD%D0%BD%D1%8B%D0%B5%20one.txt">Данные</a><a href="https://example.invalid/external">Внешняя ссылка</a><a href="mailto:example@example.invalid">Почта</a><img src="data:image/svg+xml,%3Csvg%2F%3E">')
    css(site, '/* url(missing-in-comment.png) */ .example { background: url("data:image/svg+xml,%3Csvg%2F%3E"); }')

def bad_search_index(site):
    file = site / 'search/index.html'
    text = file.read_text()
    marker = '<script type="application/json" id="search-index">'
    start = text.index(marker) + len(marker)
    end = text.index('</script>', start)
    entries = json.loads(text[start:end])
    entries[0]['url'] = '../missing-from-index/'
    payload = json.dumps(entries).replace('<', r'\u003c')
    file.write_text(text[:start] + payload + text[end:])

def bad_svg_anchor(site):
    (site / 'static/check-fixture.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><g id="existing"/></svg>')
    append_html(site, '<svg><use href="static/check-fixture.svg#missing-svg-id"></use></svg>')

def bad_symlink(site):
    outside = site.parent / 'outside.txt'
    outside.write_text('Outside build directory')
    (site / 'outside-link.txt').symlink_to(outside)
    append_html(site, '<a href="outside-link.txt">Outside</a>')

EVIDENCE.mkdir(parents=True, exist_ok=True)
original = snapshot(BUILD)
ROOT.joinpath('.cache').mkdir(exist_ok=True)
scenarios = [
    ('valid-root', lambda site: None, '/', 0, None),
    ('valid-subdir', lambda site: None, '/subdir/research-site/', 0, None),
    ('valid-encoded-anchor-inline-data', good_examples, '/', 0, None),
    ('broken-link', lambda site: append_html(site, '<a href="missing-page/">Битая ссылка</a>'), '/', 1, 'Missing file'),
    ('broken-anchor', lambda site: append_html(site, '<a href="about/#missing-anchor">Битый якорь</a>'), '/', 1, 'Missing anchor'),
    ('missing-stylesheet', lambda site: append_html(site, '<link rel="stylesheet" href="static/missing.css">'), '/', 1, 'Missing file'),
    ('missing-javascript', lambda site: append_html(site, '<script src="static/missing.js"></script>'), '/', 1, 'Missing file'),
    ('missing-image', lambda site: append_html(site, '<img src="static/missing.png">'), '/', 1, 'Missing file'),
    ('missing-srcset-image', lambda site: append_html(site, '<img srcset="data:image/svg+xml,%3Csvg%2F%3E 1x, static/missing-srcset.png 2x">'), '/', 1, 'Missing file'),
    ('broken-css-url', lambda site: css(site, '.fixture {background: url("missing-background.png")}'), '/', 1, 'Missing file'),
    ('broken-css-import', lambda site: css(site, '@import "missing-import.css";'), '/', 1, 'Missing file'),
    ('missing-font', lambda site: css(site, '@font-face {font-family: Fixture; src: url(missing-font.woff2)}'), '/', 1, 'Missing file'),
    ('empty-script', lambda site: (site / 'static/search.js').write_text(''), '/', 1, 'Empty target file'),
    ('subdir-root-url', lambda site: append_html(site, '<a href="/math/">Wrong root URL</a>'), '/subdir/research-site/', 1, 'escapes deployment base path'),
    ('broken-search-index', bad_search_index, '/', 1, 'Missing file'),
    ('broken-svg-anchor', bad_svg_anchor, '/', 1, 'Missing anchor'),
    ('symlink-outside-build', bad_symlink, '/', 1, 'escapes build directory'),
    ('duplicate-id', lambda site: append_html(site, '<p id="duplicate">a</p><p id="duplicate">b</p>'), '/', 1, 'Duplicate HTML id'),
]
results = []
try:
    with TemporaryDirectory(prefix='strict-check-test-', dir=ROOT / '.cache') as temporary:
        temporary = Path(temporary)
        for name, mutate, base_path, expected_exit, expected_message in scenarios:
            site = temporary / name
            shutil.copytree(BUILD, site, ignore=shutil.ignore_patterns('.lektor'))
            mutate(site)
            report_file = EVIDENCE / ('strict-test-' + name + '.json')
            command = [sys.executable, str(CHECKER), '--root', str(site), '--base-path', base_path, '--json', str(report_file)]
            print('$ ' + ' '.join(command), flush=True)
            process = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            print(process.stdout, flush=True)
            assert process.returncode == expected_exit, f'{name}: expected exit {expected_exit}, got {process.returncode}'
            report = json.loads(report_file.read_text())
            assert report['pass'] == (expected_exit == 0)
            if expected_message:
                assert any(expected_message in error['message'] for error in report['errors']), f'{name}: expected diagnostic not found'
            results.append({'scenario': name, 'expected_exit': expected_exit, 'actual_exit': process.returncode, 'errors': report['errors'], 'pass': True})
            print(f'PASS {name}: expected exit {expected_exit} observed.', flush=True)
finally:
    unchanged = snapshot(BUILD) == original
    final = {'pass': len(results) == len(scenarios) and unchanged, 'scenarios': results, 'build_unchanged': unchanged, 'build_files_sha256': original}
    (EVIDENCE / 'strict-tests-results.json').write_text(json.dumps(final, ensure_ascii=False, indent=2) + '\n')
    assert unchanged, 'Real build was modified by tests'
print(f'PASS all {len(results)} scenarios; real build unchanged; temporary copies removed.')
