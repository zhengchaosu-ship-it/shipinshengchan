"""原生 Elements 元数据解析安全回归，不操作真实桌面。"""
import unittest
from xiaovcat_adapter.group_identity import clean, selected_group, xpath_literal


def records(name='苏政超起号', count='2', source='339642', selected=True):
    result = [{'name': '\xa0\u200b <tr data-row-key="' + source + '">',
               'class_name': 'parent expanded' + (' selected' if selected else ''), 'level': 30}]
    for value in ['Expand …', name, count, 'Expand …', 'Expand …', 'Expand …']:
        result.append({'name': '\xa0\u200b <td class="ant-table-cell"> ' + value + ' </td> ',
                       'class_name': '', 'level': 31})
    result.append({'name': '<tr data-row-key="999">', 'class_name': 'parent', 'level': 30})
    return result


class IdentityTests(unittest.TestCase):
    def test_real_key_with_chromium_formatting(self):
        self.assertEqual(selected_group(records(), '苏政超起号', 2), '339642')

    def test_stale_selected_previous_group_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'NOT_CONFIRMED'):
            selected_group(records(), '苏政超带货', 0)

    def test_count_mismatch_rejected(self):
        with self.assertRaises(RuntimeError):
            selected_group(records(), '苏政超起号', 0)

    def test_unselected_rejected(self):
        with self.assertRaises(RuntimeError):
            selected_group(records(selected=False), '苏政超起号', 2)

    def test_duplicate_selected_rejected(self):
        with self.assertRaises(RuntimeError):
            selected_group(records() + records(), '苏政超起号', 2)

    def test_unknown_layout_rejected(self):
        a = records(); del a[4]
        with self.assertRaises(RuntimeError):
            selected_group(a, '苏政超起号', 2)

    def test_nested_metadata_not_group_name(self):
        a = records(); a[2]['level'] = 32
        with self.assertRaises(RuntimeError):
            selected_group(a, '苏政超起号', 2)

    def test_name_rename_keeps_source_key(self):
        self.assertEqual(selected_group(records(name='张三运营组'), '张三运营组', 2), '339642')

    def test_xpath_quotes(self):
        self.assertEqual(xpath_literal('a'), "'a'")
        self.assertEqual(xpath_literal("a'b"), '"a\'b"')
        self.assertEqual(xpath_literal('a\'"b'), 'concat(\'a\',"\'",\'"b\')')

    def test_formatting_normalized(self):
        self.assertEqual(clean('\xa0\u200b文本\ufeff '), '文本')
