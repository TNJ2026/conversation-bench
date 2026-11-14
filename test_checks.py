"""Checks for text constraint scoring used by v2."""
import unittest
import checks


def outcome(text, rules, earlier=()):
    return [x['pass'] for x in checks.check(text, rules, list(earlier))]

class ConstraintTests(unittest.TestCase):
    def test_constraints_fail_and_pass(self):
        rules = [{'kind':'contains','values':['2026-12-01']}, {'kind':'length','max':12}]
        self.assertEqual([x['pass'] for x in checks.check('2026-12-01',rules,[])],[True,True])
        self.assertEqual([x['pass'] for x in checks.check('x'*13,rules,[])],[False,False])

    def test_missing_paragraph_is_unscorable(self):
        rules = [{'kind':'preserve','turn':1,'paragraph':2}]
        self.assertIsNone(checks.check('text',rules,[{'answer':'one paragraph'}])[0]['pass'])
        self.assertFalse(checks.check('changed',rules,[{'answer':'first\n\nsecond'}])[0]['pass'])
        self.assertTrue(checks.check('second',rules,[{'answer':'first\n\nsecond'}])[0]['pass'])

    def test_equivalent_date_notations_count_as_kept(self):
        rules = [{'kind':'dates','values':['2026-12-15','2027-01-03']}]
        for text in ('2026-12-15 与 2027-01-03', '2026年12月15日启用，2027年1月3日审查',
                     '2026/12/15、2027/1/3', '2026.12.15—2027.01.03', '2026 年 12 月 15 日，2027 年 1 月 3 日'):
            with self.subTest(text=text):
                self.assertEqual(outcome(text, rules), [True])
        self.assertEqual(outcome('2026-12-15，另一个日期删掉了', rules), [False])
        self.assertEqual(outcome('2026-12-16 与 2027-01-03', rules), [False])
        self.assertEqual(outcome('12026-12-150 与 2027-01-03', rules), [False])

    def test_date_without_year_needs_manual_review(self):
        rules = [{'kind':'dates','values':['2026-12-15','2026-12-18']}]
        self.assertEqual(outcome('12月15日启用，12月18日审查', rules), [None])
        self.assertEqual(outcome('2026-12-15启用，12月18日审查', rules), [None])
        self.assertEqual(outcome('12月15日启用', rules), [False])

    def test_wrong_year_is_not_treated_as_an_omitted_year(self):
        rules = [{'kind':'dates','values':['2026-12-15','2026-12-18']}]
        for text in ('2027年12月15日启用，2027年12月18日审查',
                     '2026年12月15日启用，2027 年 12 月 18 日审查',
                     '12月15日启用，2027年12月18日审查'):
            with self.subTest(text=text):
                self.assertEqual(outcome(text, rules), [False])
        self.assertEqual(outcome('2026年12月15日启用，12月18日审查', rules), [None])

    def test_paragraphs_survive_windows_newlines_and_padded_blank_lines(self):
        for text in ('one\n\ntwo\n\nthree', 'one\r\n\r\ntwo\r\n\r\nthree', 'one\n \t\ntwo\n\n\n\nthree\n', '\n\none\n\ntwo\n\nthree'):
            with self.subTest(text=text):
                self.assertEqual(checks.paragraphs(text), ['one','two','three'])
        rules = [{'kind':'preserve','turn':1,'paragraph':2}]
        self.assertEqual(outcome('intro\r\ntwo\r\n', rules, [{'answer':'one\r\n\r\ntwo\r\n\r\nthree'}]), [True])
        self.assertEqual(outcome('line a\r\nline b', rules, [{'answer':'one\n\nline a\nline b'}]), [True])

    def test_layout_rules(self):
        rules = [{'kind':'paragraphs','count':4}, {'kind':'no_heading'}, {'kind':'paragraph','index':2,'value':'固定句。'}]
        self.assertEqual(outcome('一\n\n固定句。\n\n三\n\n四', rules), [True,True,True])
        self.assertEqual(outcome('# 标题\n\n一\n\n固定句。\n\n三\n\n四', rules), [False,False,False])
        self.assertEqual(outcome('## 标题\n一\n\n固定句。\n\n三\n\n四', rules), [True,False,True])
        self.assertEqual(outcome('一\n\n固定句。补了一句\n\n三\n\n四', rules), [True,True,False])
        self.assertEqual(outcome('一\n\n三\n\n四\n\n固定句。', rules), [True,True,False])
        self.assertEqual(outcome('只有一段，编号#1不是标题', rules), [False,True,False])

    def test_labels_describe_what_was_checked(self):
        label = lambda rule: checks.check('x', [rule], [])[0]['check']
        self.assertEqual(label({'kind':'contains','label':'保留固定句','values':['y']}), '保留固定句')
        self.assertNotIn('日期', label({'kind':'contains','values':['y']}))
        self.assertEqual(label({'kind':'length','max':5}), '非空白字符上限')
        self.assertEqual(label({'kind':'length','min':2,'max':5}), '非空白字符范围')
        self.assertEqual(label({'kind':'length','min':2}), '非空白字符下限')

    def test_length_bounds_are_optional_and_ignore_whitespace(self):
        self.assertEqual(outcome('a b\nc', [{'kind':'length','min':3,'max':3}]), [True])
        self.assertEqual(outcome('ab', [{'kind':'length','min':3}]), [False])
        self.assertEqual(outcome('a'*999, [{'kind':'length','min':3}]), [True])

    def test_unknown_rule_is_reported_instead_of_skipped(self):
        result = checks.check('text', [{'kind':'regex','pattern':'x'}], [])
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]['pass'])
        self.assertIn('regex', result[0]['check'])

class HtmlTests(unittest.TestCase):
    def test_section_ignores_tags_in_comments_and_raw_script_or_style(self):
        for embedded in ('<!-- example: <section> -->', '<!-- example: </section> -->',
                         '<script>const example = "<section></section>";</script>',
                         '<script>const example = "</section>";</script>',
                         '<style>/* <section> */</style>'):
            with self.subTest(embedded=embedded):
                original = '<section id="overview">before' + embedded + 'after</section>'
                self.assertEqual(checks.section(original, 'overview'), original)
                self.assertNotEqual(checks.section(original, 'overview'),
                                    checks.section(original.replace('after', 'changed'), 'overview'))
        fake = '<!-- <section id="overview">fake</section> -->'
        actual = '<section id="overview">real</section>'
        self.assertEqual(checks.section(fake + actual, 'overview'), actual)

    def test_section_keeps_original_spelling_entities_and_line_endings(self):
        original = '<SECTION\r\n data-note="a>b" ID=overview>A&amp;B\r\n<section>inner</section>tail</SECTION >'
        self.assertEqual(checks.section('prefix\r\n' + original + 'suffix', 'overview'), original)

    def test_section_includes_nested_sections(self):
        page = '<main><section class="a" id="overview"><section>inner</section>tail</section><SECTION ID=\'risks\'>r</SECTION></main>'
        self.assertEqual(checks.section(page,'overview'), '<section class="a" id="overview"><section>inner</section>tail</section>')
        self.assertEqual(checks.section(page,'risks'), "<SECTION ID='risks'>r</SECTION>")

    def test_section_absent_unclosed_or_only_a_similar_attribute(self):
        self.assertIsNone(checks.section('<section id="overview">x</section>','risks'))
        self.assertIsNone(checks.section('<section id="risks">never closed','risks'))
        self.assertIsNone(checks.section('<section data-id="risks">x</section>','risks'))
        self.assertIsNone(checks.section('<div id="risks">x</div>','risks'))

    def test_linked_resources(self):
        self.assertEqual(checks.linked_resources('<script src="https://cdn.example.com/x.js"></script>'), ['https://cdn.example.com/x.js'])
        self.assertEqual(checks.linked_resources("<link rel=stylesheet href='style.css'><img alt='' src=chart.png>"), ['style.css','chart.png'])
        self.assertEqual(checks.linked_resources('<style>@import "theme.css"; body{background:url(//example.com/bg.png)}</style>'),
                         ['//example.com/bg.png','theme.css'])

    def test_self_contained_page_has_no_linked_resources(self):
        page = ('<style>body{background:url(data:image/png;base64,AAAA)}</style><script>var src="x.js"</script>'
                '<img alt="" src="data:image/png;base64,AAAA"><a href="https://example.com/more">更多</a><a href="#risks">风险</a>')
        self.assertEqual(checks.linked_resources(page), [])


if __name__ == '__main__':
    unittest.main()
