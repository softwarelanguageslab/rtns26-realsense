#!/usr/bin/env python3
"""Check captured paper objects against a separate, current manuscript checkout."""
import argparse
import json
from pathlib import Path
import re
import subprocess


def check(package, manuscript):
    manifest = json.loads((package / 'SOURCE_MANIFEST.json').read_text())
    checks = []
    for entry in manifest['files']:
        if not entry['path'].startswith(('paper/objects/', 'paper/figures/')):
            continue
        source = manuscript / entry['origin'].split('/', 1)[1]
        expected = source.read_text()
        if 'label' in entry:
            blocks = [m.group() for m in re.finditer(
                r'(?m)^\\begin\{(figure\*?|table\*?)\}.*?^\\end\{\1\}', expected, re.S)
                if r'\label{' + entry['label'] + '}' in m.group()]
            if len(blocks) != 1:
                raise ValueError(f'Expected one active object: {entry["label"]}')
            expected = blocks[0] + '\n'
        checks.append({'path': entry['path'],
                       'matches_manuscript': (package / entry['path']).read_text() == expected})
    process = subprocess.run(['git', '-C', str(manuscript), 'rev-parse', 'HEAD'],
                             capture_output=True, text=True)
    return {'recorded_manuscript_commit': manifest['manuscript_commit'],
            'current_manuscript_commit': process.stdout.strip() if process.returncode == 0 else None,
            'all_match': all(c['matches_manuscript'] for c in checks), 'checks': checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manuscript', type=Path, required=True)
    args = parser.parse_args()
    result = check(Path(__file__).resolve().parent, args.manuscript.resolve())
    print(json.dumps(result, indent=2))
    if not result['all_match']:
        raise SystemExit('Captured objects differ from the current manuscript.')


if __name__ == '__main__':
    main()
