"""Check a built static site without network access; return 1 for broken links/resources."""
import argparse
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
import posixpath
import xml.etree.ElementTree as ET

import tinycss2


def srcset_urls(value):
    position = 0
    while position < len(value):
        while position < len(value) and (value[position].isspace() or value[position] == ','):
            position += 1
        start = position
        while position < len(value) and not value[position].isspace():
            position += 1
        url = value[start:position]
        if not url:
            break
        if url.endswith(','):
            yield url.rstrip(',')
            continue
        depth = 0
        while position < len(value):
            char = value[position]
            position += 1
            if char == '(':
                depth += 1
            elif char == ')':
                depth = max(0, depth - 1)
            elif char == ',' and not depth:
                break
        yield url


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.duplicates = []
        self.refs = []
        self.styles = []
        self.base = None
        self.capture = None
        self.parts = []
        self.indexes = []
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        line = self.getpos()[0]
        identifier = attrs.get('id')
        if identifier is not None:
            if identifier in self.ids:
                self.duplicates.append((line, identifier))
            self.ids.add(identifier)
        if tag == 'a' and attrs.get('name'):
            self.ids.add(attrs['name'])
        if tag == 'base' and self.base is None and 'href' in attrs:
            self.base = attrs['href']
        for key in ('src', 'poster', 'data'):
            if key in attrs and (key != 'data' or tag == 'object'):
                self.refs.append((attrs[key], 'resource', line))
        for key in ('srcset', 'imagesrcset'):
            for url in srcset_urls(attrs.get(key, '')):
                self.refs.append((url, 'resource', line))
        for key in ('href', 'xlink:href'):
            if key in attrs and tag != 'base':
                kind = 'link' if tag in ('a', 'area') or (tag == 'link' and attrs.get('rel') == 'canonical') else 'resource'
                self.refs.append((attrs[key], kind, line))
        for key in ('action', 'formaction'):
            if key in attrs:
                self.refs.append((attrs[key], 'link', line))
        if 'style' in attrs:
            self.styles.append((attrs['style'], line, True))
        if tag == 'style':
            self.capture, self.parts, self.capture_line = 'style', [], line
        elif tag == 'script' and attrs.get('id') == 'search-index':
            self.capture, self.parts, self.capture_line = 'index', [], line

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, text):
        if self.capture:
            self.parts.append(text)

    def handle_endtag(self, tag):
        if self.capture == 'style' and tag == 'style':
            self.styles.append((''.join(self.parts), self.capture_line, False))
            self.capture = None
        elif self.capture == 'index' and tag == 'script':
            self.indexes.append((''.join(self.parts), self.capture_line))
            self.capture = None


class Checker:
    def __init__(self, root, base_path, origin):
        self.root = root.resolve()
        self.base = '/' + base_path.strip('/') + '/' if base_path.strip('/') else '/'
        self.origin = origin.rstrip('/')
        self.errors = []
        self.counts = Counter()
        self.documents = {}

    def error(self, source, line, reference, message):
        self.errors.append({'source': source.relative_to(self.root).as_posix(), 'line': line, 'reference': reference, 'message': message})

    def file_url(self, file):
        relative = file.relative_to(self.root).as_posix()
        if relative.endswith('index.html') and (relative == 'index.html' or relative.endswith('/index.html')):
            relative = relative[:-len('index.html')]
        return self.origin + self.base + relative

    def reference(self, source, line, value, kind, base_url):
        self.counts['references'] += 1
        value = value.strip()
        if not value and kind == 'resource':
            self.error(source, line, value, 'Empty resource URL')
            return
        try:
            url = urlsplit(urljoin(base_url, value))
            if url.scheme in ('mailto', 'tel', 'sms') and kind == 'link':
                self.counts['non_file_links_skipped'] += 1
                return
            if url.scheme == 'data':
                self.counts['embedded_resources_skipped'] += 1
                return
            if url.scheme not in ('http', 'https'):
                self.error(source, line, value, 'Unsupported URL scheme')
                return
            if url.scheme + '://' + url.netloc != self.origin:
                if kind == 'link':
                    self.counts['external_links_skipped'] += 1
                else:
                    self.error(source, line, value, 'External resource cannot be verified offline; use a local resource')
                return
            decoded = unquote(url.path)
            if '\\' in decoded or '\x00' in decoded:
                self.error(source, line, value, 'Invalid URL path')
                return
            normalized = posixpath.normpath(decoded)
            mount = self.base.rstrip('/')
            if mount and normalized != mount and not normalized.startswith(mount + '/'):
                self.error(source, line, value, 'URL escapes deployment base path ' + self.base)
                return
            relative = normalized[len(mount):].lstrip('/') if mount else normalized.lstrip('/')
            target = (self.root / relative).resolve()
            if not target.is_relative_to(self.root):
                self.error(source, line, value, 'URL escapes build directory')
                return
            if target.is_dir():
                target = target / 'index.html'
            if not target.is_file():
                self.error(source, line, value, 'Missing file: ' + target.relative_to(self.root).as_posix())
                return
            if target.stat().st_size == 0:
                self.error(source, line, value, 'Empty target file: ' + target.relative_to(self.root).as_posix())
                return
            fragment = unquote(url.fragment).split(':~:text=', 1)[0]
            if fragment and fragment.lower() != 'top':
                ids = None
                if target.suffix.lower() in ('.html', '.htm'):
                    if target not in self.documents:
                        self.documents[target] = Document(target.read_text(encoding='utf-8'))
                    ids = self.documents[target].ids
                elif target.suffix.lower() == '.svg':
                    ids = {node.get('id') for node in ET.parse(target).iter() if node.get('id')}
                if ids is not None:
                    self.counts['anchors'] += 1
                    if fragment not in ids:
                        self.error(source, line, value, 'Missing anchor: #' + fragment)
                        return
            self.counts['local_references_ok'] += 1
        except (OSError, ValueError, UnicodeError, ET.ParseError) as error:
            self.error(source, line, value, type(error).__name__ + ': ' + str(error))

    def css(self, source, text, base_url, line_offset=0, inline=False):
        nodes = tinycss2.parse_component_value_list(text, skip_comments=True) if inline else tinycss2.parse_stylesheet(text, skip_comments=True, skip_whitespace=True)
        def visit(tokens):
            for token in tokens:
                line = getattr(token, 'source_line', 1) + line_offset
                if token.type == 'error':
                    self.error(source, line, '', 'CSS parse error: ' + token.message)
                elif token.type == 'url':
                    self.reference(source, line, token.value, 'resource', base_url)
                elif token.type == 'function' and token.lower_name == 'url':
                    arguments = [item for item in token.arguments if item.type not in ('whitespace', 'comment')]
                    if len(arguments) == 1 and arguments[0].type == 'string':
                        self.reference(source, line, arguments[0].value, 'resource', base_url)
                    else:
                        self.error(source, line, tinycss2.serialize(token.arguments), 'Invalid CSS url()')
                else:
                    if token.type == 'at-rule' and token.lower_at_keyword == 'import':
                        first = next((item for item in token.prelude if item.type not in ('whitespace', 'comment')), None)
                        if first and first.type == 'string':
                            self.reference(source, line, first.value, 'resource', base_url)
                    for attribute in ('prelude', 'content', 'arguments'):
                        nested = getattr(token, attribute, None)
                        if nested:
                            visit(nested)
        visit(nodes)

    def run(self):
        html_files = sorted(file for file in self.root.rglob('*') if file.suffix.lower() in ('.html', '.htm') and file.is_file() and '.lektor' not in file.relative_to(self.root).parts)
        if not html_files:
            self.error(self.root / 'index.html', 1, '', 'No HTML files in build directory')
        for source in html_files:
            try:
                self.documents[source.resolve()] = Document(source.read_text(encoding='utf-8'))
            except (OSError, UnicodeError) as error:
                self.error(source, 1, '', 'Cannot read HTML: ' + str(error))
        self.counts['html_files'] = len(html_files)
        for source, document in list(self.documents.items()):
            base_url = self.file_url(source)
            if document.base is not None:
                base_url = urljoin(base_url, document.base)
                if urlsplit(base_url).scheme + '://' + urlsplit(base_url).netloc != self.origin:
                    self.error(source, 1, document.base, 'External HTML base URL')
            for line, identifier in document.duplicates:
                self.error(source, line, '#' + identifier, 'Duplicate HTML id')
            for value, kind, line in document.refs:
                self.reference(source, line, value, kind, base_url)
            for text, line, inline in document.styles:
                self.css(source, text, base_url, line - 1, inline)
            for text, line in document.indexes:
                try:
                    index = json.loads(text)
                    if not isinstance(index, list):
                        raise ValueError('Expected a list')
                    for entry in index:
                        if not isinstance(entry, dict) or not isinstance(entry.get('url'), str):
                            raise ValueError('Index entry must contain a URL')
                        self.reference(source, line, entry['url'], 'link', base_url)
                        self.counts['search_index_links'] += 1
                except (ValueError, TypeError) as error:
                    self.error(source, line, 'search-index', 'Invalid search index JSON: ' + str(error))
        css_files = sorted(self.root.rglob('*.css'))
        self.counts['css_files'] = len(css_files)
        for source in css_files:
            try:
                text = source.read_text(encoding='utf-8-sig')
                self.css(source, text, self.file_url(source))
            except (OSError, UnicodeError) as error:
                self.error(source, 1, '', 'Cannot read CSS: ' + str(error))
        return {'pass': not self.errors, 'root': str(self.root), 'base_path': self.base, 'origin': self.origin, 'counts': dict(self.counts), 'errors': self.errors, 'limitations': ['External navigation URLs are counted but not requested.', 'JavaScript targets computed at runtime require separate browser tests; referenced script files are checked here.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('build'))
    parser.add_argument('--base-path', default='/')
    parser.add_argument('--origin', default='https://site.invalid')
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    if not args.root.is_dir():
        parser.error('Build directory does not exist: ' + str(args.root))
    origin = urlsplit(args.origin)
    if origin.scheme not in ('http', 'https') or not origin.netloc or origin.path not in ('', '/') or origin.query or origin.fragment:
        parser.error('--origin must be an HTTP(S) origin without a path')
    if '?' in args.base_path or '#' in args.base_path or '..' in args.base_path.split('/'):
        parser.error('--base-path must be a URL path without traversal, query or fragment')
    report = Checker(args.root, args.base_path, args.origin).run()
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    for error in report['errors']:
        print(f"ERROR {error['source']}:{error['line']}: {error['reference']!r} -> {error['message']}")
    print(('PASS' if report['pass'] else 'FAIL') + ': ' + json.dumps(report['counts'], ensure_ascii=False) + f"; errors={len(report['errors'])}")
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
