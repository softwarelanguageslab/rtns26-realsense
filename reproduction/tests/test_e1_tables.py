"""Regression checks for E1 display precision and observed bounds."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'e1_workers/tables.py'
if not SOURCE.is_file():
    SOURCE = ROOT / 'code/reproduction/e1_workers/tables.py'
spec = importlib.util.spec_from_file_location('e1_tables', SOURCE)
tables = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tables)


def sample(index, **updates):
    row = dict(camera='d435', workload='representative30',
               family=tables.FAMILIES[index], instances=1,
               execution_max_us=45, interval_min_ms=5000.074,
               utilization_percent=.00096)
    row.update(updates)
    return row


class E1TableTests(unittest.TestCase):
    def test_interval_has_no_intermediate_rounding(self):
        data = [sample(0, interval_min_ms=14.3486)]
        self.assertEqual(tables.family_cells(data, 0, 'representative30')[2], '14.35')
        self.assertEqual(tables.family_cells(data, 0, 'representative30', True)[2], '14.3')

    def test_utilization_has_no_intermediate_rounding(self):
        data = [sample(4, utilization_percent=.02046)]
        self.assertEqual(tables.family_cells(data, 4, 'representative30')[3], '0.0205')
        self.assertEqual(tables.family_cells(data, 4, 'representative30', True)[3], '0.020')

    def test_display_comparison_allows_rounding_but_rejects_changed_values(self):
        self.assertTrue(tables.matches_display('14.4', (14.3486, 14.3486)))
        self.assertFalse(tables.matches_display('14.5', (14.3486, 14.3486)))
        self.assertFalse(tables.matches_display('2', (1, 1), exact=True))
        self.assertFalse(tables.matches_display(r'$<$0.001', (.001, .001)))

    def test_estimates_keep_original_precision(self):
        data = [sample(0, interval_min_ms=14.3486123, utilization_percent=1.124777594027703)]
        result = tables.family_estimates(data, 0, 'representative30')
        self.assertEqual(result[2], (14.3486123, 14.3486123))
        self.assertEqual(result[3], (1.124777594027703, 1.124777594027703))

    def test_bound_uses_unrounded_value(self):
        for value, expected in [(.0009999, r'$<$0.001'), (.001, '0.0010'), (.00101, '0.0010')]:
            with self.subTest(value=value):
                data = [sample(6, utilization_percent=value)]
                self.assertEqual(tables.family_cells(data, 6, 'representative30', True)[3], expected)

    def test_dispatcher_count_is_derived(self):
        data = [sample(7, family='Notification dispatcher') for _ in range(4)]
        self.assertEqual(tables.family_cells(data, 7, 'representative30')[0], '4')

    def test_changed_timeout_is_not_hidden(self):
        data = [sample(7, family='Pipeline dispatcher', interval_min_ms=4000)]
        self.assertEqual(tables.family_cells(data, 7, 'representative30', True)[2], '4000')

    def test_missing_family_fails(self):
        with self.assertRaisesRegex(ValueError, 'Missing E1 family'):
            tables.family_cells([], 0, 'representative30')

    def test_incomplete_template_fails(self):
        with self.assertRaisesRegex(ValueError, 'Expected 8 E1 rows'):
            tables.format_table('', [], [])


if __name__ == '__main__':
    unittest.main()
