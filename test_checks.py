"""Checks for text constraint scoring used by v2."""
import unittest
import checks


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


if __name__ == '__main__':
    unittest.main()
