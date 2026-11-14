"""Text constraints shared by the v2 study runner and its checks."""

PRODUCTS = ('dsh', 'chatgpt', 'hermes')

def check(text, rules, earlier):
    results = []
    for rule in rules:
        kind = rule['kind']
        if kind == 'contains':
            missing = [x for x in rule['values'] if x not in text]
            results.append({'check': '保留指定日期', 'pass': not missing, 'detail': '缺少：' + ', '.join(missing) if missing else '全部出现'})
        elif kind == 'length':
            length = len(''.join(text.split()))
            results.append({'check': '非空白字符上限', 'pass': rule.get('min', 0) <= length <= rule['max'], 'detail': f'{length} / {rule["max"]}；含标点及 Markdown，非语言学字数' + (f'；下限 {rule["min"]}' if 'min' in rule else '')})
        elif kind == 'preserve':
            source = earlier[rule['turn'] - 1]['answer']
            paragraphs = [p.strip() for p in source.split('\n\n') if p.strip()]
            index = rule['paragraph'] - 1
            if index >= len(paragraphs):
                results.append({'check': '保留指定段落', 'pass': None, 'detail': '原回答无法按空行识别该段，需人工审阅'})
            else:
                excerpt = paragraphs[index]
                results.append({'check': '保留指定段落', 'pass': excerpt in text, 'detail': '按空行识别，人工确认选段是否正确。原段：' + excerpt})
    return results
