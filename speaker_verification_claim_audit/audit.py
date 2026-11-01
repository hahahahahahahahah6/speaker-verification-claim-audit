"""Offline documentation and source comparison."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import sys

from . import __version__
from .phrases import VERIFY, NOVERIFY


def normalize(text):
    return ' '.join(text.lower().replace("n't", ' not').replace('-', ' ').split())


def pattern(phrases):
    return re.compile(r'\b(?:' + '|'.join(re.escape(p) for p in sorted(phrases, key=lambda p: (-len(p), p))) + r')\b')


VERIFY_RE = pattern(VERIFY)
NOVERIFY_RE = pattern(NOVERIFY)


def claims(text):
    lines = []
    fence = None
    for line in text.splitlines():
        opening = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if fence:
            if re.match(r'^ {0,3}' + re.escape(fence[0]) + '{' + str(fence[1]) + r',}\s*$', line):
                fence = None
            lines.append('')
        elif opening:
            token = opening.group(1)
            fence = (token[0], len(token))
            lines.append('')
        else:
            lines.append(line)
    positive = negative = False
    for paragraph in re.split(r'\n\s*\n', '\n'.join(lines)):
        text = normalize(paragraph)
        negative |= bool(NOVERIFY_RE.search(text))
        positive |= bool(VERIFY_RE.search(NOVERIFY_RE.sub(' ', text)))
    return positive, negative


def evidence(source):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    aliases = {}
    shadows = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
    encoder = embedding = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = aliases.get(func.id, func.id)
            if func.id in shadows:
                continue
            if name != 'VoiceEncoder' and func.id not in aliases:
                continue
        else:
            continue
        if name in shadows:
            continue
        if name in ('verify_files', 'verify_batch', 'verify_speaker', 'identify_speaker'):
            return True
        if name == 'from_pretrained':
            args = list(node.args) + [kw.value for kw in node.keywords]
            if any(isinstance(arg, ast.Constant) and isinstance(arg.value, str) and 'speaker verification' in normalize(arg.value) for arg in args):
                return True
        encoder |= name == 'VoiceEncoder'
        embedding |= name == 'embed_utterance'
    return encoder and embedding


def audit(root, ignores=()):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise OSError('root must be an accessible directory')
    positive = negative = production = test = False
    docs = []
    sources = []
    prefixes = [Path(p).as_posix().strip('/') for p in ignores]
    def ignored(relative):
        path = relative.as_posix()
        return any(path == p or path.startswith(p + '/') for p in prefixes)
    def walk_error(error):
        raise error
    for directory, dirs, files in os.walk(root, onerror=walk_error, followlinks=False):
        base = Path(directory)
        dirs[:] = sorted(d for d in dirs if not (base / d).is_symlink() and not ignored((base / d).relative_to(root)))
        for filename in sorted(files):
            path = base / filename
            relative = path.relative_to(root)
            if path.is_symlink() or ignored(relative):
                continue
            parts = relative.parts
            if relative.as_posix() == 'README.md' or (path.suffix == '.md' and 'docs' in parts[:-1]):
                p, n = claims(path.read_text(encoding='utf-8'))
                positive |= p
                negative |= n
                docs.append(relative.as_posix())
            if path.suffix == '.py':
                sources.append(relative.as_posix())
                if any(part in ('fixtures', 'docs', 'examples') for part in parts[:-1]):
                    continue
                is_test = 'tests' in parts[:-1] or filename.startswith('test_') or filename.endswith('_test.py')
                found = evidence(path.read_text(encoding='utf-8'))
                if is_test:
                    test |= found
                else:
                    production |= found
    findings = []
    if positive and not production:
        findings.append({'id': 'documented-speaker-verification-claim-false', 'severity': 'MEDIUM' if test else 'HIGH', 'message': 'Documentation promises an operation found only in tests.' if test else 'Documentation promises an operation absent from production source.'})
    if negative and production:
        findings.append({'id': 'documented-no-speaker-verification-claim-false', 'severity': 'HIGH', 'message': 'Documentation denies an operation present in production source.'})
    return {'verdict': 'FAIL' if findings else 'PASS', 'findings': findings, 'docs': docs, 'sources': sources, 'production_evidence': production, 'test_evidence': test}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, self.prog + ': error: ' + message + '\n')


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[])
    parser.add_argument('--fail-on', choices=('LOW', 'MEDIUM', 'HIGH'), default='HIGH', type=str.upper)
    args = parser.parse_args(argv)
    try:
        result = audit(args.root, args.ignore)
    except (OSError, UnicodeError) as error:
        print('error: ' + str(error), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(result['verdict'])
        for finding in result['findings']:
            print('{severity} {id}: {message}'.format(**finding))
        if args.verbose:
            print('Documents: ' + ', '.join(result['docs']))
            print('Sources: ' + ', '.join(result['sources']))
    ranks = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}
    return 2 if any(ranks[f['severity']] >= ranks[args.fail_on] for f in result['findings']) else 0
