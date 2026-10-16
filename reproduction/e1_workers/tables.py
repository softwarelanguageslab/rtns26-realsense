"""Shared E1 table formatting for the manuscript and hardware reproduction."""
from collections import defaultdict
from decimal import Decimal
import re

FAMILIES = (
    'Depth/IR capture', 'Color capture', 'Application wait', 'udev watcher',
    'Time-difference keeper', 'Thermal monitor', 'Firmware-error poller',
    'Notification/pipeline dispatchers',
)
WORKLOADS = ('representative30', 'stress60')
NAME_ALIASES = {r'Time-diff.\ keeper': 'Time-difference keeper'}


def family_estimates(data, index, workload):
    family = FAMILIES[index]
    group = [r for r in data if r['workload'] == workload and
             (r['family'] == family or (index == 7 and r['family'] in
              ('Notification dispatcher', 'Pipeline dispatcher')))]
    if not group:
        raise ValueError(f'Missing E1 family: {workload}/{family}')
    counts = [int(r['instances']) for r in group]
    if index == 7:
        per_camera = defaultdict(int)
        for row in group:
            per_camera[row['camera']] += int(row['instances'])
        counts = list(per_camera.values())
    ranges = [(min(counts), max(counts))]
    for key in ('execution_max_us', 'interval_min_ms', 'utilization_percent'):
        values = [float(row[key]) for row in group]
        ranges.append((min(values), max(values)))
    return ranges


def family_cells(data, index, workload, compact=False):
    estimates = family_estimates(data, index, workload)
    digits = [0, 0, (1 if index < 3 else 0) if compact else 2,
              ([2, 2, 3, 3, 3, 4, 4, 5] if compact else [2, 2, 3, 4, 4, 4, 4, 5])[index]]
    # Display formatting only: no intermediate rounding or changes to the CSV.
    cells = []
    for bounds, precision in zip(estimates, digits):
        low, high = (f'{v:.{precision}f}' for v in bounds)
        cells.append(low if low == high else low + '--' + high)
    if index == 7 and 4999 < estimates[2][0] <= estimates[2][1] < 5001:
        cells[2] = r'$\approx$5000' + ('' if compact else ' (idle timeout)')
    if compact and index >= 6 and 0 <= estimates[3][0] <= estimates[3][1] < .001:
        cells[3] = r'$<$0.001'
    return cells


def matches_display(display, bounds, exact=False):
    """Compare raw estimates, allowing one unit of the paper's last digit.

    This accommodates the manuscript's display rounding without reproducing
    its intermediate rounding. Counts and explicit upper bounds stay exact.
    """
    if display.startswith(r'$<$'):
        return 0 <= bounds[0] <= bounds[1] < float(display[3:])
    if display.startswith(r'$\approx$'):
        target = float(display.removeprefix(r'$\approx$').split()[0])
        return all(abs(value - target) < 1 for value in bounds)
    parts = display.split('--')
    if len(parts) == 1:
        parts *= 2
    if len(parts) != 2:
        raise ValueError(f'Unexpected numeric cell: {display}')
    return all(abs(Decimal(str(value)) - Decimal(token)) <=
               (0 if exact else Decimal(10) ** Decimal(token).as_tuple().exponent)
               for token, value in zip(parts, bounds))


def format_table(template, data, checks, full=False):
    """Rebuild every numeric cell and compare it with the captured manuscript."""
    names = list(FAMILIES) + list(NAME_ALIASES) + ['Dispatchers', r'\mbox{Thermal monitor']
    pattern = r'(?m)^    (?:' + '|'.join(map(re.escape, names)) + r').*?\\\\'
    caption_counts = {}
    if not full and 'Instances per camera' in template:
        counts = re.search(
            r'Instances per camera\s+\$n\$\s+\(R/S\):\s*Depth/IR capture\s+'
            r'(\d+)/(\d+),\s*dispatchers\s+(\d+)/(\d+),\s*others\s+(\d+)\.',
            template)
        if counts is None:
            raise ValueError('Unrecognized E1 instance counts in caption')
        depth_r, depth_s, dispatch_r, dispatch_s, other = counts.groups()
        caption_counts = {i: [other, other] for i in range(len(FAMILIES))}
        caption_counts[0] = [depth_r, depth_s]
        caption_counts[7] = [dispatch_r, dispatch_s]
    seen = set()
    index = 0
    def replace(match):
        nonlocal index
        cells = [re.sub(r'\s+', ' ', c.strip()) for c in match.group()[:-2].split('&')]
        name = cells[0]
        canonical_name = NAME_ALIASES.get(name, name)
        family_index = next((i for i, family in enumerate(FAMILIES) if family in canonical_name), None)
        if family_index is None and name.startswith('Dispatchers'):
            family_index = 7
        if family_index is None:
            raise ValueError(f'Unknown E1 row: {name}')
        workload = WORKLOADS[index // 8] if full else 'R/S'
        identity = (workload, family_index)
        if identity in seen:
            raise ValueError(f'Duplicate E1 row: {identity}')
        seen.add(identity)
        if full:
            new = family_cells(data, family_index, workload)
            old = cells[2:]
            estimates = family_estimates(data, family_index, workload)
            exact = [True, False, False, False]
            output = cells[:2] + new
        else:
            pair = [family_cells(data, family_index, w, compact=True) for w in WORKLOADS]
            new = [pair[w][col] for col in (1, 2, 3) for w in (0, 1)]
            old = [re.sub(r'^\\rg\{(.*)\}$', r'\1', c) for c in cells[1:]]
            expected_counts = re.search(r'\(\$n\$=([^/]+)/([^\)]+)\)', name)
            counts = (list(expected_counts.groups()) if expected_counts else
                      caption_counts.get(family_index, ['1', '1']))
            # Include the implicit/annotated instance counts in each row check.
            old += counts
            new += [p[0] for p in pair]
            raw = [family_estimates(data, family_index, w) for w in WORKLOADS]
            estimates = [raw[w][col] for col in (1, 2, 3, 0) for w in (0, 1)]
            exact = [False] * 6 + [True] * 2
            output = [name] + [r'\rg{' + v + '}' if not v.startswith('$') else v for v in new[:6]]
        checks.append({'object': 'supp-table-4' if full else 'main-table-2',
                       'row': f'{workload}/{FAMILIES[family_index]}',
                       'matches_paper': len(old) == len(estimates) and all(
                           matches_display(value, bounds, count)
                           for value, bounds, count in zip(old, estimates, exact)),
                       'paper': old, 'rebuilt': new, 'unrounded_ranges': estimates})
        index += 1
        return '    ' + ' & '.join(output) + ' ' + chr(92) * 2
    result = re.sub(pattern, replace, template, flags=re.S)
    expected = 16 if full else 8
    if index != expected:
        raise ValueError(f'Expected {expected} E1 rows, found {index}')
    return result
