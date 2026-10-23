import io,json,sys,unittest,zipfile
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import earnings_schedule as s
NOW=datetime(2026,10,23,tzinfo=timezone.utc)
ROWS=[{'A':'2026年10月22日 現在'},{'A':'決算発表予定日','B':'コード','C':'会社名','E':'決算期末','H':'種別'},
      {'A':'46318','B':'6146','C':'合成会社','E':'46477','H':'第2四半期'},
      {'A':'46319','B':'9999','C':'対象外'},{'A':'未定','B':'6146'}]
class ScheduleTests(unittest.TestCase):
 def test_only_verified_members_and_specific_dates(self):
  with patch.object(s,'worksheet',return_value=ROWS): items,asof=s.parse_schedule(b'',{'6146':'合成会社'},s.SOURCE)
  self.assertEqual(len(items),1);self.assertEqual(items[0]['stage'],'planned');self.assertEqual(asof,'2026-10-22');self.assertNotIn('published_at',items[0]);self.assertNotIn('profit',items[0])
 def test_schema_fail_closed(self):
  with patch.object(s,'worksheet',return_value=[{'A':'changed'}]):
   with self.assertRaises(ValueError):s.parse_schedule(b'',{},s.SOURCE)
 def test_failure_preserves_last_schedule(self):
  old={'items':[{'date':'2026-10-26'}],'last_success_at':'2026-10-22'}
  result=s.update_schedule(NOW,lambda *a: (_ for _ in ()).throw(OSError()),{},old)
  self.assertEqual(result['state'],'failed');self.assertEqual(result['items'],old['items']);self.assertEqual(result['last_success_at'],old['last_success_at'])
 def test_links_bounded_and_official_only(self):
  calls=[]
  def dl(url,hosts):calls.append(url);return b'<a href="https://evil.example/kessan09_1023.xlsx">bad</a>'
  self.assertEqual(s.update_schedule(NOW,dl,{})['state'],'failed');self.assertEqual(len(calls),1)
 def test_snapshot_and_independent_plan_state(self):
  def dl(url,hosts):return b'<a href="/listing/event-schedules/financial-announcement/kessan09_1023.xlsx">schedule</a>'
  with patch.object(s,'worksheet',return_value=ROWS):result=s.update_schedule(NOW,dl,{'6146':'合成会社'})
  self.assertEqual(result['state'],'success');self.assertEqual(len(result['items']),1);self.assertEqual(result['sources'][0]['as_of'],'2026-10-22')
 def test_zip_entry_limit(self):
  b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:
   for i in range(101):z.writestr(str(i),'')
  with self.assertRaises(ValueError):s.worksheet(b.getvalue())
