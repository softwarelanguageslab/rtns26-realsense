#!/usr/bin/env python3
"""Build the 12 current paper objects from audited measurements and source layouts."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

PACKAGE = Path(__file__).resolve().parents[1]


def rows(path):
    with path.open(newline='') as source:
        return list(csv.DictReader(source))


def rounded(value, digits, intermediate=None):
    value = Decimal(str(value))
    if intermediate is not None:
        value = value.quantize(Decimal(10) ** -intermediate, rounding=ROUND_HALF_UP)
    return f'{value:.{digits}f}'


def span(group, key, digits, intermediate=None):
    values = [float(row[key]) for row in group]
    low, high = (rounded(x, digits, intermediate) for x in (min(values), max(values)))
    return low if low == high else low + '--' + high


def family_table(template, derived, checks, full=False):
    from reproduction.e1_workers.tables import format_table
    return format_table(template, rows(derived / 'e1_workers/e1_families.csv'), checks, full)


def overhead_table(template, derived, age, checks):
    data = {(r['workload'], r['mode']): r for r in rows(derived / 'e4_scheduling/overhead_summary.csv')}
    keys = ['sensor_age_ms_mean', 'sensor_age_ms_p99', 'sensor_age_ms_max',
            'backend_to_return_ms_p99', 'arrival_to_return_ms_p99'] if age else [
            'cpu_percent', 'rss_max_mib', 'interarrival_mean_ms', 'interarrival_p99_ms',
            'interarrival_max_ms', 'trace_mib']
    index = 0
    pattern = r'(?m)^\s*(?:(?:Representative, 30 FPS|Stress, 60 FPS)?\s*&\s*)?(?:Off|Build-only|Full)\s*&.*?\\\\'
    def replace(match):
        nonlocal index
        mode = ['off', 'build-only', 'full'][index % 3]
        workload = 'stress' if age or index >= 3 else 'representative'
        cells = [s.strip() for s in match.group()[:-2].split('&')]
        offset = 1 if age else 2
        old = cells[offset:]
        values = [rounded(data[workload, mode][key], len(value.split('.')[1]) if '.' in value else 0)
                  for key, value in zip(keys, old)]
        checks.append({'object': 'supp-table-2' if age else 'supp-table-1',
                       'row': f'{workload}/{mode}', 'matches_paper': old == values,
                       'paper': old, 'rebuilt': values})
        index += 1
        return '\n    ' + ' & '.join(cells[:offset] + values) + r' \\'
    result = re.sub(pattern, replace, template, flags=re.S)
    if index != (3 if age else 6):
        raise ValueError('Unexpected overhead table layout')
    return result


def patterns(raw):
    counts = Counter()
    sources = []
    root = raw / 'results/e2_uvc_pool/formal/d1-uvc5-standard-hardirq'
    markers = sorted(root.glob('**/run-*/selected_attempt.txt'))
    if len(markers) != 6:
        raise ValueError('Expected six accepted URB5 runs')
    for marker in markers:
        path = marker.parent / ('attempt-' + marker.read_text().strip()) / 'frame_events.csv'
        sources.append({'path': str(path.relative_to(raw)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        deliveries = defaultdict(dict)
        for row in rows(path):
            deliveries[row['camera_index'], int(row['delivery'])][row['stream'], row['stream_index']] = int(row['frame_number'])
        previous = {}; history = []
        for (camera, delivery), current in deliveries.items():
            prior = previous.get(camera)
            previous[camera] = current
            if prior is None:
                continue
            delta = {s: n - prior[s] for s, n in current.items()}
            history.append((30 if len(current) == 2 else 60, delta))
        for i, (fps, delta) in enumerate(history):
            reused = {s for s, n in delta.items() if n == 0}
            if reused:
                following = history[i + 1][1] if i + 1 < len(history) else {}
                if not all(following.get(s) == 2 for s in reused):
                    raise ValueError('Reuse is not followed by the expected single-frame gap')
                if reused == {('Depth', '0')}:
                    counts[fps, 'depth-only'] += 1
                elif reused == {('Depth', '0'), ('Infrared', '1'), ('Infrared', '2')}:
                    counts[fps, 'depth-ir'] += 1
                else:
                    raise ValueError(f'Unexpected reuse pattern: {reused}')
            elif all(n == 2 for n in delta.values()):
                counts[fps, 'all-stream-gap'] += 1
            elif any(n != 1 for n in delta.values()):
                # A catch-up return is already represented by its preceding reuse.
                prior_reuse = {s for s, n in history[i - 1][1].items() if n == 0} if i else set()
                if {s for s, n in delta.items() if n == 2} != prior_reuse or any(n not in (1, 2) for n in delta.values()):
                    raise ValueError('Unclassified freshness pattern')
    return counts, sources


def host_path_figure(template, derived, checks):
    uvc = {(r['fps'], int(r['urbs'])): r for r in rows(derived / 'e2_uvc_pool/uvc_pool.csv')}
    bar_index = 0
    def e2(match):
        nonlocal bar_index
        fps = ('30 FPS', '60 FPS')[bar_index // 2]
        key = ('partially_stale', 'framesets_with_gaps')[bar_index % 2]
        value = uvc[fps, 5][key]
        checks.append({'object': 'main-figure-4a', 'matches_paper': match[2] == value})
        bar_index += 1
        return match[1] + value + ');'
    result = re.sub(r'(\\fill\[uvcfive\] \([0-9.]+,0\) rectangle \([0-9.]+,)([0-9]+)\);', e2, template)
    if bar_index != 4 or any(int(r[k]) for (fps,u),r in uvc.items() if u == 16 for k in ('partially_stale','framesets_with_gaps')):
        raise ValueError('Unexpected E2 plot structure or nonzero URB16 count')
    data = {(r['camera'], r['treatment']): r for r in rows(derived / 'e3_kernel_path/e3_summary.csv')}
    treatments = ['xhci-other_uvc-other', 'xhci-fifo90_uvc-other', 'xhci-fifo90_uvc-fifo89']
    index = 0
    def e3bar(match):
        nonlocal index
        camera = ('d435', 'd455')[index % 2]; treatment = treatments[index // 2]
        y = math.log10(float(data[camera,treatment]['nonfresh_percent'])) + 2
        value = f'{y:.3f}'
        checks.append({'object': 'main-figure-4b-height', 'matches_paper': match[2] == value})
        index += 1
        return match[1] + value + ');'
    result = re.sub(r'(\\fill\[d4(?:35|55)line\] \([0-9.]+,0\) rectangle \([0-9.]+,)([0-9.]+)\);', e3bar, result)
    if index != 6:
        raise ValueError('Expected six E3 bars')
    index = 0
    def label(match):
        nonlocal index
        camera = ('d435', 'd455')[index % 2]; treatment = treatments[index // 2]
        value = f'{float(data[camera,treatment]["nonfresh_percent"]):.{3 if index >= 4 else 2}f}'
        checks.append({'object': 'main-figure-4b-label', 'matches_paper': match[2] == value})
        index += 1
        return match[1] + value + '};'
    result = re.sub(r'(\\node\[text=d4(?:35|55)line[^\n]+\{)([0-9.]+)\};', label, result)
    if index != 6:
        raise ValueError('Expected six E3 labels')
    return result


def render(directory):
    if not shutil.which('pdflatex'):
        raise RuntimeError('PDF output needs TeX Live: texlive-latex-extra texlive-pictures')
    for source in sorted(directory.glob('*.tex')):
        text = source.read_text()
        # Standalone objects retain the paper widths; captions are kept in the .tex sources.
        body = re.sub(r'\\begin\{(?:figure|table)\*?\}(?:\[[^]]*\])?', '', text)
        body = re.sub(r'\\end\{(?:figure|table)\*?\}', '', body)
        start = body.find(r'\caption{')
        while start >= 0:
            depth = 1; end = start + len(r'\caption{')
            while depth:
                if body[end] == '{': depth += 1
                if body[end] == '}': depth -= 1
                end += 1
            body = body[:start] + body[end:]
            start = body.find(r'\caption{')
        body = re.sub(r'\\label\{[^}]+\}', '', body)
        with tempfile.TemporaryDirectory(prefix='paper-object-') as temporary:
            work = Path(temporary)
            shutil.copytree(directory / 'figures', work / 'figures')
            (work / 'main.tex').write_text(r'''\documentclass[border=4pt]{standalone}
\usepackage[T1]{fontenc}
\usepackage{graphicx,booktabs,array,tikz,pgfplots}
\usetikzlibrary{arrows.meta,calc,decorations.pathreplacing,fit,positioning}
\pgfplotsset{compat=1.18}
\begin{document}
\begin{minipage}{12.2cm}\centering
''' + body + '\n'+r'\end{minipage}\end{document}'+'\n')
            process = subprocess.run(['pdflatex','-halt-on-error','-interaction=nonstopmode','main.tex'],
                                     cwd=work, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            source.with_suffix('.render.log').write_text(process.stdout)
            if process.returncode:
                raise RuntimeError(f'PDF rendering failed: {source.name}')
            shutil.copyfile(work / 'main.pdf', source.with_suffix('.pdf'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--derived', type=Path, required=True)
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pdf', action='store_true')
    args = parser.parse_args()
    out = args.output; out.mkdir(parents=True, exist_ok=False)
    checks = []
    for source in sorted((PACKAGE / 'paper/objects').glob('*.tex')):
        text = source.read_text()
        if source.stem == 'tab-steady-model-validation': text = family_table(text, args.derived, checks)
        elif source.stem == 'tab-steady-model-validation-full': text = family_table(text, args.derived, checks, full=True)
        elif source.stem == 'tab-instrumentation-overhead': text = overhead_table(text, args.derived, False, checks)
        elif source.stem == 'tab-instrumentation-age-overhead': text = overhead_table(text, args.derived, True, checks)
        elif source.stem == 'fig-linux-host-path-results': text = host_path_figure(text, args.derived, checks)
        elif source.stem == 'tab-uvc-freshness-patterns':
            counts, sources = patterns(args.raw)
            replacements = {'2 at 30 FPS; 1 at 60 FPS': f'{counts[30,"depth-only"]} at 30 FPS; {counts[60,"depth-only"]} at 60 FPS',
                            '9 at 60 FPS': f'{counts[60,"depth-ir"]} at 60 FPS', '3 at 60 FPS': f'{counts[60,"all-stream-gap"]} at 60 FPS'}
            for old, new in replacements.items():
                checks.append({'object': 'supp-table-3', 'matches_paper': old == new, 'paper': old, 'rebuilt': new})
                text = text.replace(old, new)
            (out / 'freshness-patterns.json').write_text(json.dumps({'counts':{f'{k[0]}/{k[1]}':v for k,v in counts.items()},'sources':sources},indent=2)+'\n')
        (out / source.name).write_text(text)
    (out / 'figures').mkdir()
    for metric, name in [('p99','main-matrix-host-latency-tikz.tex'),('max','main-matrix-host-latency-max-tikz.tex')]:
        source = args.derived / 'e4_scheduling' / f'e4-{metric}.tex'
        reference = PACKAGE / 'paper/figures' / name
        checks.append({'object': 'main-figure-5' if metric == 'p99' else 'supp-figure-1',
                       'matches_paper':source.read_bytes() == reference.read_bytes(), 'comparison':'byte-identical TikZ'})
        shutil.copyfile(source, out / 'figures' / name)
    report = {'checks': checks, 'all_match': all(c['matches_paper'] for c in checks),
              'object_count':len(list(out.glob('*.tex'))),
              'manual_objects':['fig-linux-usb-path','fig-thread-temporal-model','fig-timing-notions','tab-experiment-populations'],
              'e1_rounding':'Unrounded estimates are retained in CSVs and E1 validation ranges. LaTeX uses ordinary formatting without intermediate rounding. E1 paper comparisons allow one unit of the last displayed digit; counts and <0.001 bounds are exact.'}
    (out / 'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['object_count'] != 12 or not report['all_match']:
        raise ValueError(f'Paper comparison failed; inspect {out / "validation.json"}')
    if args.pdf:
        render(out)
    print(f'Regenerated {report["object_count"]} paper objects; {len(checks)} comparisons passed.')


if __name__ == '__main__':
    main()
