"""仅通过原生 DevTools Elements 的公开无障碍树读取分组 DOM 键。

不运行 Console/JavaScript，不使用 CDP、网络或 CatBridge，不修改源数据。
DevTools 的 DOM 无障碍树是平铺结构，需使用 aria level 而非 UIA 父子关系。
"""
import re
import time


def clean(text):
    return re.sub('[\u200b\u200c\u200d\ufeff]', '', str(text)).strip()


def xpath_literal(value):
    if "'" not in value:
        return "'" + value + "'"
    if '"' not in value:
        return '"' + value + '"'
    return "concat(" + ',"\'",'.join("'" + part + "'" for part in value.split("'")) + ")"


def selected_group(records, expected_name, expected_count):
    candidates = []
    for i, row in enumerate(records):
        name = clean(row['name'])
        match = re.fullmatch(r'<tr\b[^>]*\bdata-row-key="([0-9]+)"[^>]*>.*', name)
        if not match or 'selected' not in row['class_name'].split():
            continue
        level = row['level']
        if level is None:
            continue
        cells = []
        for child in records[i + 1:]:
            if child['level'] is None:
                continue
            if child['level'] <= level:
                break
            if child['level'] == level + 1 and clean(child['name']).startswith('<td '):
                cells.append(clean(child['name']))
        if len(cells) != 6:
            continue
        # 必须取得当前选中行的名称和数量，不按行序号匹配源ID。
        text = lambda cell: re.fullmatch(r'<td\b[^>]*>\s*(.*?)\s*</td>', cell)
        n, count = text(cells[1]), text(cells[2])
        if n and count and n[1] == expected_name and count[1] == str(expected_count):
            candidates.append(match[1])
    if len(candidates) != 1:
        raise RuntimeError('GROUP_DOM_IDENTITY_NOT_CONFIRMED')
    return candidates[0]


def selected_metadata(records, expected_id):
    """按当前 DOM 的稳定键识别单组；名称只从同一行读取。"""
    matches = []
    for i, row in enumerate(records):
        key = re.match(r'<tr\b[^>]*\bdata-row-key="([0-9]+)"', clean(row['name']))
        if not key or key[1] != expected_id or 'selected' not in row['class_name'].split():
            continue
        level = row['level']
        if level is None:
            continue
        cells = []
        for child in records[i + 1:]:
            if child['level'] is None:
                continue
            if child['level'] <= level:
                break
            if child['level'] == level + 1 and clean(child['name']).startswith('<td '):
                cells.append(clean(child['name']))
        if len(cells) != 6:
            continue
        name = re.fullmatch(r'<td\b[^>]*>\s*(.*?)\s*</td>', cells[1])
        count = re.fullmatch(r'<td\b[^>]*>\s*(\d+)\s*</td>', cells[2])
        if name and name[1] and count:
            matches.append({'group_name': name[1], 'account_count': int(count[1])})
    if len(matches) != 1:
        raise RuntimeError('GROUP_DOM_IDENTITY_NOT_CONFIRMED')
    return matches[0]


class NativeGroupIdentity:
    def __init__(self, ui, trace=None):
        self.ui = ui
        self.uia = ui.uia
        self.trace = trace
        self.last_records = []

    def log(self, stage, status='START', **details):
        if self.trace:
            self.trace.emit(stage, status, **details)

    def find(self, name):
        return self.uia.root(self.ui.hwnd).FindFirst(4, self.uia.client.CreatePropertyCondition(30005, name))

    def wait(self, check, stage='GROUP_SWITCH_FAILED', step=None):
        self.log(stage, step=step)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            value = check()
            if value:
                self.log(stage, 'OK', step=step)
                return value
            time.sleep(.12)
        self.log(stage, 'TIMEOUT', selected_rows=[
            {k: r[k] for k in ('name', 'class_name', 'level')}
            for r in self.last_records if 'selected' in r['class_name'].split()
            or r['name'].startswith('<td ')][:12])
        raise RuntimeError(stage + ': EXPECTED_DOM_STATE_TIMEOUT')

    def keys(self, codes):
        from .desktop_worker.keyboard_driver import native_user
        user = native_user()
        if user.GetForegroundWindow() != self.ui.hwnd:
            raise RuntimeError('GROUP_DOM_FOREGROUND_CHANGED_NEEDS_MANUAL')
        for code in codes:
            user.keybd_event(code, 0, 0, 0)
        for code in reversed(codes):
            user.keybd_event(code, 0, 2, 0)

    def records(self):
        root = self.uia.root(self.ui.hwnd)
        dom = root.FindFirst(4, self.uia.client.CreatePropertyCondition(30012, 'elements-tree-outline source-code'))
        if not dom:
            raise RuntimeError('GROUP_DOM_TREE_NOT_FOUND')
        # DevTools 的公开树在部分 Chromium 版本中跨虚拟容器平铺；
        # 确认 Elements DOM 容器存在，再遍历 TreeItem，只使用选中分组行投影。
        items = root.FindAll(4, self.uia.client.CreatePropertyCondition(30003, 50024))
        records = []
        try:
            for i in range(items.Length):
                e = items.GetElement(i)
                props = str(e.CurrentAriaProperties)
                level = re.search(r'(?:^|;)level=(\d+)(?:;|$)', props)
                records.append({'name': clean(e.CurrentName), 'class_name': str(e.CurrentClassName),
                                'level': int(level[1]) if level else None, 'element': e})
        except Exception:
            # DOM刷新会使整批元素失效，整批舍弃，外层有截止时间地重新观察。
            return []
        self.last_records = records
        return records

    def query_row(self, query, group, panel_id, target_group_id):
        # 每次尝试重新取得根/页面/搜索框；不复用上一轮的 COM 句柄。
        root = self.uia.root(self.ui.hwnd)
        panel = root.FindFirst(4, self.uia.client.CreatePropertyCondition(30011, panel_id))
        elements = self.find('Elements')
        if not panel or not elements or 'selected' not in str(elements.CurrentClassName):
            raise RuntimeError('GROUP_LIST_NOT_READY: PAGE_CHANGED')
        self.log('GROUP_LIST_NOT_READY', 'OK', step='RECONFIRM_PAGE', group_id=target_group_id)
        def search_value():
            return self.find('Find by string, selector, or XPath').GetCurrentPattern(10002).QueryInterface(
                self.uia.types.IUIAutomationValuePattern)
        search_value().SetValue(query)
        self.wait(lambda: search_value().CurrentValue == query, step='SEARCH_QUERY_READBACK')
        self.find('Find by string, selector, or XPath').SetFocus()
        self.wait(lambda: self.uia.client.CompareElements(self.uia.client.GetFocusedElement(),
                  self.find('Find by string, selector, or XPath')), step='SEARCH_FOCUS')
        self.keys([0x0D])

        def selected():
            records = self.records()
            rows = [r for r in records if 'selected' in r['class_name'].split()
                    and re.match(r'<tr\b[^>]*\bdata-row-key=', r['name'])]
            if len(rows) != 1:
                return None
            key = re.search(r'\bdata-row-key="([0-9]+)"', rows[0]['name'])
            if not key or target_group_id and key[1] != target_group_id:
                return None
            return rows[0]

        node = self.wait(selected, 'GROUP_NODE_NOT_FOUND', 'SELECT_EXACT_GROUP')
        self.log('GROUP_NODE_NOT_FOUND', 'OK', step='READ_DATA_ROW_KEY',
                 group_id=re.search(r'data-row-key="([0-9]+)"', node['name'])[1])

        def confirmed():
            # DOM刷新可能使刚选中的句柄失效，重新取树并重新确认 ID 后再展开。
            node = selected()
            if not node:
                return None
            if 'expanded' not in node['class_name'].split():
                node['element'].GetCurrentPattern(10005).QueryInterface(
                    self.uia.types.IUIAutomationExpandCollapsePattern).Expand()
                return None
            try:
                records = self.records()
                if target_group_id:
                    group.update(selected_metadata(records, target_group_id))
                    return target_group_id
                return selected_group(records, group['group_name'], group['account_count'])
            except RuntimeError:
                return None
        return self.wait(confirmed, 'GROUP_SWITCH_FAILED', 'EXPAND_AND_READ_GROUP_ROW')

    def query_with_retry(self, query, group, panel_id, target_group_id):
        for attempt in range(3):  # 初次读取 + 最多两次重试。
            try:
                return self.query_row(query, group, panel_id, target_group_id)
            except (RuntimeError, OSError, self.uia.com_error) as error:
                if 'FOREGROUND_CHANGED' in str(error) or 'PAGE_CHANGED' in str(error):
                    raise
                self.log('GROUP_SWITCH_FAILED', 'RETRY' if attempt < 2 else 'FAILED',
                         attempt=attempt + 1, group_id=target_group_id, cause=str(error))
                if attempt == 2:
                    raise

    def read(self, groups, panel_id, target_group_id=None):
        if self.find('Elements'):
            raise RuntimeError('EXISTING_DEVTOOLS_NEEDS_MANUAL')
        opened = False
        try:
            self.keys([0x11, 0x10, 0x49])
            opened = True
            elements = self.wait(lambda: self.find('Elements'), step='OPEN_ELEMENTS')
            elements.GetCurrentPattern(10010).QueryInterface(self.uia.types.IUIAutomationSelectionItemPattern).Select()
            self.wait(lambda: 'selected' in str(self.find('Elements').CurrentClassName))
            self.find('Elements').SetFocus()
            self.wait(lambda: self.uia.client.CompareElements(self.uia.client.GetFocusedElement(), self.find('Elements')))
            self.keys([0x11, 0x46])
            self.wait(lambda: self.find('Find by string, selector, or XPath'))
            result = []
            for group in ([{'group_id': target_group_id}] if target_group_id else groups):
                query = ('//div[@id=' + xpath_literal(panel_id) + ']//tr[@data-row-key=' +
                         xpath_literal(target_group_id) + ']') if target_group_id else (
                         '//div[@id=' + xpath_literal(panel_id) + ']//tr[@data-row-key]'
                         '[td[normalize-space(.)=' + xpath_literal(group['group_name']) + ']]')
                source_id = self.query_with_retry(query, group, panel_id, target_group_id)
                self.log('GROUP_SWITCH_FAILED', 'OK', step='GROUP_METADATA_VERIFIED', group_id=source_id,
                         group_name=group['group_name'], account_count=group['account_count'])
                result.append({**group, 'group_id': source_id, 'source_group_id': source_id,
                               'identity_status': 'SOURCE_ID',
                               'identity_evidence': {'source': 'NATIVE_DEVTOOLS_ACCESSIBLE_DOM',
                                                     'property': 'data-row-key', 'selector': query,
                                                     'name_and_count_readback': True}})
            if len({g['group_id'] for g in result}) != len(result):
                raise RuntimeError('DUPLICATE_SOURCE_GROUP_ID')
            return result
        finally:
            if opened and self.find('Elements'):
                self.find('Elements').SetFocus()
                self.keys([0x11, 0x10, 0x49])
                self.wait(lambda: not self.find('Elements'))
