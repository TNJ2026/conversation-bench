"""Text constraints shared by the v2 study runner and its checks."""
import re
from html.parser import HTMLParser

PRODUCTS = ('dsh', 'chatgpt', 'hermes')
KINDS = ('contains', 'dates', 'length', 'paragraphs', 'paragraph', 'no_heading', 'preserve',
         'exact', 'json', 'excludes', 'sentences')

FULL_DATE = re.compile(r'(?<!\d)(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})(?!\d)')
MONTH_DAY = re.compile(r'(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})(?!\d)')
HEADING = re.compile(r'^[ \t]{0,3}#{1,6}[ \t]*\S', re.M)
RESOURCE = re.compile(r'<(?:script|img|iframe|video|audio|source|embed|link)\b[^>]*?\s(?:src|href)\s*=\s*'
                      r'(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))', re.I)
CSS_URL = re.compile(r'url\(\s*["\']?([^"\')]+)', re.I)
CSS_IMPORT = re.compile(r'@import\s+["\']([^"\']+)', re.I)


def normalize(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')

def without_digit_separators(text):
    """Treat 28,000 as 28000 so formatting is not mistaken for a missing figure."""
    return re.sub(r'(?<=\d)[,\uFF0C](?=\d)', '', text)

def paragraphs(text):
    return [p.strip() for p in re.split(r'\n\s*\n', normalize(text)) if p.strip()]

class _SectionParser(HTMLParser):
    """Locate a section without changing its original source text or whitespace."""
    def __init__(self, page, name):
        super().__init__(convert_charrefs=False)
        self.page, self.name = page, name
        self.lines = [0] + [m.end() for m in re.finditer('\n', page)]
        self.start, self.depth, self.result = None, 0, None

    def source_offset(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag != 'section' or self.result is not None:
            return
        if self.start is None:
            if dict(attrs).get('id') != self.name:
                return
            self.start = self.source_offset()
        self.depth += 1

    def handle_startendtag(self, tag, attrs):
        # Section is not a void element: <section/> still opens a section in HTML.
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag != 'section' or self.depth == 0 or self.result is not None:
            return
        self.depth -= 1
        if self.depth == 0:
            end = self.page.find('>', self.source_offset()) + 1
            self.result = self.page[self.start:end]


def section(page, name):
    """Return original section HTML, ignoring tag-shaped comments and script/style text."""
    parser = _SectionParser(page, name)
    parser.feed(page)
    parser.close()
    return parser.result

class _ResourceParser(HTMLParser):
    """Static resource references only; comments and JavaScript strings are not tags."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = []
        self.in_style = False

    def css(self, text):
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
        self.found.extend(CSS_URL.findall(text))
        self.found.extend(CSS_IMPORT.findall(text))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'style': self.in_style = True
        if attrs.get('style'): self.css(attrs['style'])
        keys = {'script': ('src',), 'img': ('src',), 'iframe': ('src',),
                'video': ('src', 'poster'), 'audio': ('src',), 'source': ('src',),
                'embed': ('src',), 'link': ('href',), 'object': ('data',),
                'track': ('src',), 'input': ('src',), 'image': ('href', 'xlink:href'),
                'use': ('href', 'xlink:href')}.get(tag, ())
        self.found.extend(attrs[k] for k in keys if attrs.get(k))
        if tag in ('img', 'source', 'link'):
            # HTML srcset URL tokens may contain commas (notably data: URLs).
            # Descriptors end at the next comma; trailing commas delimit bare URLs.
            rest = attrs.get('srcset') or attrs.get('imagesrcset') or ''
            while rest.strip(' ,\t\r\n'):
                rest = rest.lstrip(' ,\t\r\n')
                match = re.match(r'\S+', rest)
                url = match.group(); rest = rest[match.end():]
                self.found.append(url.rstrip(','))
                if not url.endswith(','):
                    comma = rest.find(',')
                    rest = rest[comma + 1:] if comma >= 0 else ''

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if tag == 'style': self.in_style = False

    def handle_data(self, text):
        if self.in_style: self.css(text)


def linked_resources(page):
    """Static references, not proof of offline behavior (dynamic JS needs browser review)."""
    parser = _ResourceParser()
    parser.feed(page); parser.close()
    return [v.strip() for v in parser.found if v.strip() and not v.strip().lower().startswith(('data:', '#'))]

def check_dates(text, values):
    dates = list(FULL_DATE.finditer(text))
    present = {f'{m[1]}-{int(m[2]):02}-{int(m[3]):02}' for m in dates}
    # A full date with a different year must not masquerade as a yearless date.
    yearless_text = FULL_DATE.sub(lambda m: ' ' * len(m.group()), text)
    without_year = {(int(m), int(d)) for m, d in MONTH_DAY.findall(yearless_text)}
    missing = [v for v in values if v not in present]
    if not missing:
        return True, '指定日期均出现；只核对存在性，不验证事件归属或排除额外错误日期（支持等价日期写法）'
    ambiguous = [v for v in missing if tuple(int(x) for x in v.split('-')[1:]) in without_year]
    if len(ambiguous) == len(missing):
        return None, '只出现缺少年份的写法，需人工确认：' + ', '.join(missing)
    return False, '缺少：' + ', '.join(missing)

SENTENCE_END = re.compile(r'[。！？!?]+')

def sentences(text):
    """Sentences ended by Chinese or Western terminal punctuation; trailing text without one also counts."""
    return [part.strip() for part in SENTENCE_END.split(normalize(text)) if part.strip()]

def check(text, rules, earlier):
    results = []
    for rule in rules:
        kind = rule['kind']
        if kind == 'contains':
            haystack = without_digit_separators(text)
            missing = [x for x in rule['values'] if without_digit_separators(x) not in haystack]
            results.append({'check': rule.get('label', '包含指定文本'), 'pass': not missing, 'detail': '缺少：' + ', '.join(missing) if missing else '全部出现'})
        elif kind == 'dates':
            passed, detail = check_dates(text, rule['values'])
            results.append({'check': rule.get('label', '保留指定日期'), 'pass': passed, 'detail': detail})
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
        elif kind == 'exact':
            results.append({'check': rule.get('label', '回答与指定值一致'), 'pass': text.strip() == rule['value'],
                            'detail': '去掉首尾空白后整条回复须等于 ' + repr(rule['value']) + '；附加任何说明都判不一致'})
        elif kind == 'json':
            import json
            try:
                parsed = json.loads(text.strip())
                if 'keys' in rule:
                    problem = None if isinstance(parsed, dict) and set(parsed) == set(rule['keys']) else '不是只含指定键的JSON对象'
                else:
                    problem = None if parsed == rule['value'] else '键或值与预期不同'
            except ValueError:
                problem = '整条回复不是可解析的JSON（代码围栏或前后说明也会导致失败）'
            results.append({'check': rule.get('label', 'JSON与预期一致'), 'pass': problem is None,
                            'detail': (problem or '解析结果与预期对象完全相同') + '；键顺序不限，数字与字符串类型须一致'})
        elif kind == 'excludes':
            found = [x for x in rule['values'] if x in text]
            results.append({'check': rule.get('label', '不含指定文本'), 'pass': not found,
                            'detail': '出现：' + ', '.join(found) if found else '均未出现；只做字面匹配，换说法需人工确认'})
        elif kind == 'sentences':
            count = len(sentences(text))
            results.append({'check': rule.get('label', '句数'), 'pass': count == rule['count'],
                            'detail': f'按句末标点（。！？!?）识别 {count} 句，要求 {rule["count"]} 句；启发式，省略号、引号内句号需人工确认'})
        else:
            results.append({'check': '未知检查类型：' + str(kind), 'pass': None, 'detail': '当前版本无法执行该检查，需人工审阅'})
    return results
