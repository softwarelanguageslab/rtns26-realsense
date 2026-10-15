"""Export E1's compact R/S table and supplementary precision table."""
from pathlib import Path
from analysis_common import module, rows


def plot(data, repo):
    tables = module('e1_tables', Path(__file__).with_name('tables.py'))
    values = rows(data / 'e1_families.csv')
    compact = [r'\begingroup\footnotesize', r'\setlength{\tabcolsep}{2pt}',
               r'\begin{tabular}{@{}lrrrrrr@{}}', r'\toprule',
               r'Worker family & \multicolumn{2}{c}{$\widehat C$ ($\mu$s)} & '
               r'\multicolumn{2}{c}{$\widehat T/\widehat\Delta$ (ms)} & '
               r'\multicolumn{2}{c}{$U^{\mathrm{obs}}$ (\%)} \\',
               r' & R & S & R & S & R & S \\', r'\midrule']
    for i, family in enumerate(tables.FAMILIES):
        if i in (0, 3, 7):
            category = {0: 'Frame-triggered', 3: 'Timer-triggered', 7: 'Event-triggered (idle timeout)'}[i]
            compact.append(r'\multicolumn{7}{@{}l}{\emph{' + category + r'}} \\')
        pair = [tables.family_cells(values, i, w, compact=True) for w in tables.WORKLOADS]
        name = 'Dispatchers' if i == 7 else family
        if i == 5:
            name += ' (D455)'
        if i == 7 or any(p[0] != '1' for p in pair):
            name += ' ($n$=' + '/'.join(p[0] for p in pair) + ')'
        compact.append(' & '.join([name] + [pair[w][col] for col in (1, 2, 3) for w in (0, 1)]) + r' \\')
    compact += [r'\bottomrule\end{tabular}', r'\endgroup']
    (data / 'e1-families.tex').write_text('\n'.join(compact) + '\n')

    full = [r'\begingroup\scriptsize', r'\setlength{\tabcolsep}{2pt}']
    for workload, label in zip(tables.WORKLOADS, ('R', 'S')):
        full += [r'\begin{tabular}{@{}llrrrr@{}}', r'\toprule',
                 r'Worker family & Activation & $n_' + label + r'$ & $\widehat C$ ($\mu$s) & '
                 r'$\widehat T/\widehat\Delta$ (ms) & $U^{\mathrm{obs}}$ (\%) \\', r'\midrule']
        for i, family in enumerate(tables.FAMILIES):
            activation = 'Frame' if i < 3 else 'Timer' if i < 7 else 'Event/timeout'
            name = family + (' (D455 only)' if i == 5 else '')
            full.append(' & '.join([name, activation] + tables.family_cells(values, i, workload)) + r' \\')
        full += [r'\bottomrule\end{tabular}', r'\par\smallskip']
    full += [r'\endgroup']
    (data / 'e1-families-full.tex').write_text('\n'.join(full) + '\n')
