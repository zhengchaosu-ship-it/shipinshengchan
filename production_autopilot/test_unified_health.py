import json,sqlite3,unittest
from .unified_health import project,legacy_issue


class UnifiedHealthTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE media_execution_settings(key TEXT,value TEXT);
        INSERT INTO media_execution_settings VALUES('enabled','true'),('publisher_execution_node','WORKER-2060S-01'),('server_provider_upload','DISABLED');
        CREATE TABLE media_execution_worker_health(worker_id TEXT,received_at REAL,details_json TEXT);
        CREATE TABLE media_account_publish_gates(business_account_id TEXT,gate TEXT,provider_account_status TEXT);
        INSERT INTO media_account_publish_gates VALUES('a','OPEN','ONLINE');
        CREATE TABLE media_publisher_infrastructure(worker_id TEXT,state TEXT);
        INSERT INTO media_publisher_infrastructure VALUES('WORKER-2060S-01','ONLINE');''')
        self.detail={'status':'READY','render':{'render_capability':'READY'},'yixiaoer_local_ready':True,'network':{'state':'ONLINE'}}
        self.rows=[{'component':'Publisher Worker','state':'STALE'},{'component':'Render Worker','state':'OFFLINE'},
                   {'component':'Yixiaoer Client','state':'OK'},{'component':'Render输出目录','state':'OK'}]

    def view(self,**kwargs):
        self.db.execute('DELETE FROM media_execution_worker_health')
        self.db.execute('INSERT INTO media_execution_worker_health VALUES(?,?,?)',('WORKER-2060S-01',99,json.dumps(self.detail)))
        before=self.db.total_changes
        result={r['component']:r for r in project(self.db,self.rows,now=kwargs.get('now',100))}
        self.assertEqual(self.db.total_changes,before)
        return result

    def test_stale_legacy_and_disabled_server_upload_not_production_fault(self):
        v=self.view();self.assertNotIn('Publisher Worker',v);self.assertNotIn('Render Worker',v)
        self.assertTrue(all(r['state']=='OK' for r in v.values()))

    def test_busy_and_attention_never_offline_while_heartbeat_fresh(self):
        for status in ('BUSY','NEEDS_ATTENTION','WAITING_FOR_WORKSTATION'):
            self.detail['status']=status
            self.assertEqual(self.view()['2060执行节点']['state'],'OK')
        self.detail['status']='NEEDS_ATTENTION'
        self.assertEqual(self.view()['渲染能力']['state'],'BLOCKED')

    def test_output_directory_not_evidence_of_online(self):
        v=self.view(now=200)
        self.assertEqual(v['Render输出目录']['state'],'OK');self.assertEqual(v['2060执行节点']['state'],'OFFLINE')

    def test_account_gate_separate_from_local_client(self):
        self.db.execute("UPDATE media_account_publish_gates SET gate='BLOCKED_RISK'")
        v=self.view();self.assertEqual(v['Yixiaoer Client']['state'],'OK');self.assertEqual(v['发布能力']['state'],'BLOCKED')

    def test_degraded_automation_blocks_render_only(self):
        self.detail['jianying_automation']={'state':'DEGRADED'}
        v=self.view();self.assertEqual(v['渲染能力']['state'],'BLOCKED');self.assertEqual(v['发布能力']['state'],'OK')

    def test_only_legacy_system_issue_hidden(self):
        self.assertTrue(legacy_issue({'account_id':'__SYSTEM__','reason':'Publisher Worker：STALE'}))
        self.assertFalse(legacy_issue({'account_id':'a','reason':'ACCOUNT_RISK'}))
        self.assertFalse(legacy_issue({'account_id':'__SYSTEM__','reason':'磁盘空间：LOW'}))

    def test_legacy_mode_remains_compatible(self):
        self.db.execute("UPDATE media_execution_settings SET value='false' WHERE key='enabled'")
        self.assertEqual(project(self.db,self.rows),self.rows)
