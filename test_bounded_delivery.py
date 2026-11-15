import json,unittest
import bounded_delivery as b

class BoundedDeliveryTests(unittest.TestCase):
 def setUp(self):
  self.originals=[dict(seq=13,text='核验时间能否提前未知。'),dict(seq=14,text='预算更新为新值；建议未批准。')]
  self.e=b.evidence_packet(self.originals);self.draft='A-1：code（原文）\nA-2：other（原文）\n\n结论：不能确认按期。\n';self.edit=b.editable_paragraph(self.draft)
  self.guard=b.validate_guards([dict(seq=13,quote='能否提前未知')],self.originals,self.e['packet'])
  self.patch=dict(replacement='结论：核验能否提前未知，建议未批准。',source_ids=['s13@0','s14@0'],unresolved=[])
 def apply(self,obj=None,reason='completed'):return b.apply_repair(self.draft,b.dump(self.patch if obj is None else obj),reason,self.e,self.edit,self.guard)
 def test_packet_has_a_hard_bound_and_reports_omissions(self):
  sources=self.originals+[dict(seq=n,text='long '+('x'*10000)) for n in range(20,50)]
  e=b.evidence_packet(sources,max_chars=1200)
  self.assertLessEqual(len(e['text']),1200);self.assertFalse(e['packet']['complete_source_copy']);self.assertTrue(e['selection']['omitted_ranges'])
  for item in e['packet']['items']:self.assertEqual(item['text'],next(s['text'] for s in sources if s['seq']==item['seq'])[item['start_char']:item['end_char']])
 def test_only_selected_paragraph_changes_and_status_guard_is_written(self):
  r=self.apply();self.assertTrue(r['accepted']);self.assertIn('能否提前未知',r['answer'])
  self.assertEqual(r['answer'][:self.edit['start']],self.draft[:self.edit['start']]);self.assertTrue(r['answer'].endswith('\n'));self.assertIsNone(r['task_success'])
 def test_truncated_or_malformed_repair_never_erases_correct_lines(self):
  for raw,reason in (('', 'max-tokens'),('{"replacement":','max-tokens'),('not json','completed'),('[]','completed')):
   r=b.apply_repair(self.draft,raw,reason,self.e,self.edit,self.guard);self.assertFalse(r['accepted']);self.assertEqual(r['answer'],self.draft)
 def test_false_source_missing_guard_overlength_and_unresolved_rejected(self):
  for change in (dict(source_ids=['s40@0']),dict(replacement='结论：不能按期。'),dict(replacement='x'*181),dict(unresolved=['Unknown evidence gap']),dict(replacement='line1\nline2')):
   obj={**self.patch,**change};r=self.apply(obj);self.assertFalse(r['accepted']);self.assertEqual(r['answer'],self.draft)
 def test_reported_source_uncertainty_is_not_a_patch_defect(self):
  obj={**self.patch,'replacement':'核验时间能否提前未知；建议未批准。','unresolved':[]}
  r=self.apply(obj);self.assertTrue(r['accepted'])
  self.assertIn('能否提前未知',r['answer']);self.assertIn('建议未批准',r['answer'])
  blocked=self.apply({**obj,'unresolved':['Required receipt outside editable paragraph is incorrect']})
  self.assertFalse(blocked['accepted']);self.assertEqual(blocked['answer'],self.draft)
 def test_source_guards_cannot_inject_scoring_keys_or_unseen_text(self):
  with self.assertRaises(ValueError):b.validate_guards([dict(seq=40,quote='fake')],self.originals,self.e['packet'])
  with self.assertRaises(ValueError):b.validate_guards([dict(seq=13,quote='wrong')],self.originals,self.e['packet'])
 def test_exact_bounds_with_unicode_and_duplicate_explicit_span(self):
  d='😀prefix\n\n结论：待定。';edit=b.editable_paragraph(d);r=b.apply_repair(d,b.dump(self.patch),'completed',self.e,edit,self.guard)
  self.assertTrue(r['answer'].startswith('😀prefix\n\n'))
  with self.assertRaises(ValueError):b.editable_paragraph('same\n\nsame','same')
 def test_packet_requires_admitted_unique_sources(self):
  with self.assertRaises(ValueError):b.evidence_packet([self.originals[0],self.originals[0]])
 def test_missing_source_or_bad_edit_binding_does_not_silently_repair(self):
  r=self.apply({**self.patch,'source_ids':[]});self.assertFalse(r['accepted'])
  edit={**self.edit,'start':0}
  with self.assertRaises(ValueError):b.apply_repair(self.draft,b.dump(self.patch),'completed',self.e,edit,self.guard)

if __name__=='__main__':unittest.main()
