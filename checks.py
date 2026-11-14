"""Text constraints shared by the v2 study runner and its checks."""
import re

PRODUCTS = ('dsh', 'chatgpt', 'hermes')
KINDS = ('contains', 'dates', 'length', 'paragraphs', 'paragraph', 'no_heading', 'preserve')

FULL_DATE = re.compile(r'(?<!\d)(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})(?!\d)')
MONTH_DAY = re.compile(r'(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})(?!\d)')
HEADING = re.compile(r'^[ \t]{0,3}#{1,6}[ \t]*\S', re.M)
SECTION_TAG = re.compile(r'<(/?)section\b[^>]*>', re.I)
RESOURCE = re.compile(r'<(?:script|img|iframe|video|audio|source|embed|link)\b[^>]*?\s(?:src|href)\s*=\s*'
                      r'(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))', re.I)
CSS_URL = re.compile(r'url\(\s*["\']?([^"\')]+)', re.I)
CSS_IMPORT = re.compile(r'@import\s+["\']([^"\']+)', re.I)


def normalize(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')

def paragraphs(text):
    return [p.strip() for p in re.split(r'\n\s*\n', normalize(text)) if p.strip()]

def section(page, name):
    """Return the complete section with this id, including nested sections."""
    opening = re.search(rf'<section\b[^>]*\sid\s*=\s*["\']{re.escape(name)}["\'][^>]*>', page, re.I)
    if not opening:
        return None
    depth = 1
    for tag in SECTION_TAG.finditer(page, opening.end()):
        depth += -1 if tag.group(1) else 1
        if depth == 0:
            return page[opening.start():tag.end()]
    return None

def linked_resources(page):
    """Resources a single offline file would have to load from elsewhere."""
    found = [next(v for v in m.groups() if v is not None) for m in RESOURCE.finditer(page)]
    found += CSS_URL.findall(page) + CSS_IMPORT.findall(page)
    return [v.strip() for v in found if v.strip() and not v.strip().lower().startswith(('data:', '#'))]

def check_dates(text, values):
    present = {f'{y}-{int(m):02}-{int(d):02}' for y, m, d in FULL_DATE.findall(text)}
    without_year = {(int(m), int(d)) for m, d in MONTH_DAY.findall(text)}
    missing = [v for v in values if v not in present]
    if not missing:
        return True, '全部出现（年-月-日、年/月/日及中文年月日写法视为等价）'
    ambiguous = [v for v in missing if tuple(int(x) for x in v.split('-')[1:]) in without_year]
    if len(ambiguous) == len(missing):
        return None, '只出现缺少年份的写法，需人工确认：' + ', '.join(missing)
    return False, '缺少：' + ', '.join(missing)

def check(text, rules, earlier):
    results = []
    for rule in rules:
        kind = rule['kind']
        if kind == 'contains':
            missing = [x for x in rule['values'] if x not in text]
            results.append({'check': rule.get('label', '包含指定文本'), 'pass': not missing, 'detail': '缺少：' + ', '.join(missing) if missing else '全部出现'})
        elif kind == 'dates':
            passed, detail = check_dates(text, rule['values'])
            results.append({'check': '保留指定日期', 'pass': passed, 'detail': detail})
        elif kind == 'length':
            length = len(''.join(text.split()))
            low, high = rule.get('min'), rule.get('max')
            label = '非空白字符下限' if high is None else '非空白字符范围' if low is not None else '非空白字符上限'
            measured = f'{length} / {high}' if high is not None else str(length)
            results.append({'check': label, 'pass': (low is None or low <= length) and (high is None or length <= high),
                            'detail': measured + '；含标点及 Markdown，非语言学字数' + (f'；下限 {low}' if low is not None else '')})
        elif kind == 'paragraphs':
            count = len(paragraphs(text))
            results.append({'check': '段落数', 'pass': count == rule['count'],
                            'detail': f'按空行识别 {count} 段，要求 {rule["count"]} 段；回答文件只应包含正文，引导语会被计为一段'})
        elif kind == 'paragraph':
            parts = paragraphs(text)
            index = rule['index'] - 1
            actual = parts[index] if index < len(parts) else None
            results.append({'check': f'第{rule["index"]}段原样', 'pass': actual == rule['value'],
                            'detail': '按空行识别。实际：' + actual if actual is not None else '按空行识别不到该段'})
        elif kind == 'no_heading':
            headings = HEADING.findall(normalize(text))
            results.append({'check': '不加标题', 'pass': not headings,
                            'detail': ('发现 Markdown 标题行' if headings else '未发现 Markdown 标题行') + '；其他形式的标题需人工确认'})
        elif kind == 'preserve':
            parts = paragraphs(earlier[rule['turn'] - 1]['answer'])
            index = rule['paragraph'] - 1
            if index >= len(parts):
                results.append({'check': '保留指定段落', 'pass': None, 'detail': '原回答无法按空行识别该段，需人工审阅'})
            else:
                excerpt = parts[index]
                results.append({'check': '保留指定段落', 'pass': excerpt in normalize(text), 'detail': '按空行识别，人工确认选段是否正确。原段：' + excerpt})
        else:
            results.append({'check': '未知检查类型：' + str(kind), 'pass': None, 'detail': '当前版本无法执行该检查，需人工审阅'})
    return results
