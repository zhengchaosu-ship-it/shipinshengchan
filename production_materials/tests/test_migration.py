from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from production_materials.config import settings
from production_materials.library import pool_roots
from production_materials.migration import choose_target, stage_file, remove_verified_source, safe_path, bind_references
from production_materials.store import Store, ProductionMaterialCatalog


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='pm-migration-')
        self.root=Path(self.temp.name);self.old=self.root/'legacy';self.new=self.root/'library'
        self.old.mkdir();self.new.mkdir()

    def tearDown(self):self.temp.cleanup()

    def row(self,name='same.mp4',data=b'media fixture'):
        p=self.old/name;p.write_bytes(data)
        return dict(source_path=str(p),target_path=str(self.new/name),file_size=len(data),sha256=hashlib.sha256(data).hexdigest())

    def test_copy_then_verified_source_removal(self):
        r=self.row();stage_file(r,[self.old],self.new)
        self.assertTrue(Path(r['source_path']).exists())
        remove_verified_source(r,[self.old],self.new)
        self.assertFalse(Path(r['source_path']).exists());self.assertTrue(self.old.is_dir())
        remove_verified_source(r,[self.old],self.new)  # 崩溃恢复可重入。

    def test_duplicate_and_different_hash_no_overwrite(self):
        r=self.row();p=Path(r['target_path']);p.write_bytes(b'existing')
        renamed,duplicate=choose_target(p,r['sha256'],{})
        self.assertFalse(duplicate);self.assertEqual(renamed.name,'same__001.mp4')
        with self.assertRaisesRegex(ValueError,'COLLISION'):stage_file(r,[self.old],self.new)
        self.assertEqual(p.read_bytes(),b'existing');self.assertTrue(Path(r['source_path']).exists())
        reserved={};a,d=choose_target(self.new/'b.mp4',r['sha256'],reserved)
        b,d=choose_target(self.new/'b.mp4',r['sha256'],reserved)
        self.assertEqual(a,b);self.assertTrue(d)

    def test_changed_target_retains_source(self):
        r=self.row();stage_file(r,[self.old],self.new);Path(r['target_path']).write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'TARGET_CHANGED'):remove_verified_source(r,[self.old],self.new)
        self.assertTrue(Path(r['source_path']).is_file())

    def test_changed_source_retains_source(self):
        r=self.row();Path(r['source_path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):stage_file(r,[self.old],self.new)
        self.assertFalse(Path(r['target_path']).exists())

    def test_protected_and_path_escape(self):
        with self.assertRaisesRegex(ValueError,'OUTSIDE'):safe_path(self.root/'raw.mp4',[self.old])
        with self.assertRaisesRegex(ValueError,'PROTECTED'):safe_path(self.old/'raw.mp4',[self.old],[self.old])

    def test_catalog_scans_commerce_and_keeps_scope(self):
        c=dict(settings(),database=str(self.root/'catalog.db'),products_file='')
        s=Store(c);s.initialize([dict(pool_id='COMMERCE_PRODUCT_INTRO',module_type='COMMERCE_PRODUCT_INTRO',
            business_type='COMMERCE',label='述品介绍',root=str(self.old))]);s.add_product('product_a','A')
        self.row();self.assertEqual(s.metadata_inventory(),1)
        cat=ProductionMaterialCatalog(c);items=cat.for_commerce('product_a','COMMERCE_PRODUCT_INTRO')
        self.assertEqual(len(items),1);self.assertEqual(items[0]['product_scope'],'GLOBAL')
        self.assertEqual(cat.query(business_type='VISUAL'),[])
        self.assertEqual(cat.query(product_id='product_a',exact_scope=True),[])

    def test_binding_preserves_identity_lineage_and_templates(self):
        from production_materials.config import ROOT
        fixture=self.root/'project';(fixture/'jianying_auto').mkdir(parents=True);(fixture/'production_materials').mkdir()
        roots=pool_roots(self.new)
        for root in roots.values():root.mkdir(parents=True,exist_ok=True)
        source=self.old/'a.mp4';source.write_bytes(b'fixture');target=roots['STARTUP_LEAD']/'a.mp4';target.write_bytes(b'fixture')
        cfg=dict(settings(),database=str(self.root/'catalog.db'),shadow_db=str(self.root/'shadow.db'),operations_db=str(self.root/'ops.db'),products_file='')
        pools=[]
        for key,path in roots.items():
            module={'STARTUP_LEAD':'STARTUP_HOOK','STARTUP_CLOSE':'STARTUP_ENDING'}.get(key,key)
            pools.append(dict(pool_id=module,module_type=module,business_type='STARTUP' if key.startswith('STARTUP') else 'COMMERCE' if key.startswith('COMMERCE') else 'VISUAL',label=key,root=str(self.old)))
        s=Store(cfg);s.initialize(pools)
        digest=hashlib.sha256(b'fixture').hexdigest()
        with s.connect(True) as db:
            db.execute('''INSERT INTO materials(material_id,business_type,module_type,pool_id,product_scope,original_filename,stored_filename,path,content_hash,size_bytes,mtime_ns,duration,width,height,media_type,status,created_at)
                VALUES('PM-stable','STARTUP','STARTUP_HOOK','STARTUP_HOOK','GLOBAL','original.mp4','a.mp4',?,?,7,1,1,10,10,'VIDEO','LIBRARY_READY','original-time')''',(str(source),digest))
        with closing(sqlite3.connect(cfg['shadow_db'])) as db,db:
            db.executescript('''CREATE TABLE composition_material_pools(account_id,pool_id,label,root);
                CREATE TABLE composition_catalog_cache(account_id,pool_id,file_key,path,size_bytes,mtime_ns,media_sha256,PRIMARY KEY(account_id,pool_id,file_key));
                CREATE TABLE shadow_profiles(business_account_id,catalog_json,template_json);
                INSERT INTO shadow_profiles VALUES('account','[]','untouched template');''')
            db.execute('INSERT INTO composition_material_pools VALUES(?,?,?,?)',('account','old-template-pool','引流',str(self.old)))
        with closing(sqlite3.connect(cfg['operations_db'])) as db,db:
            db.executescript((ROOT/'account_visuals/migrations/001_background.sql').read_text('utf-8'))
            db.execute('CREATE TABLE autopilot_authorizations(enabled)')
        for relative,value in [('jianying_auto/config.json',{'pull_dir':str(self.old)}),('jianying_auto/jianying_source_folders.json',{'引流':str(self.old)}),('production_materials/service.config.json',{})]:
            (fixture/relative).write_text(json.dumps(value),encoding='utf-8')
        plan=dict(config=cfg,destination=str(self.new),sources=[dict(root=str(self.old),target=str(roots['STARTUP_LEAD']))],rows=[dict(source_path=str(source),target_path=str(target),material_id='PM-stable',pool_id='STARTUP_LEAD',business_type='STARTUP',sha256=digest)])
        with patch('production_materials.migration.ROOT',fixture):bind_references(plan)
        with s.connect() as db:
            row=dict(db.execute('SELECT * FROM materials').fetchone())
            self.assertEqual(row['material_id'],'PM-stable');self.assertEqual(row['original_filename'],'original.mp4')
            self.assertEqual(row['module_type'],'STARTUP_HOOK');self.assertEqual(row['content_hash'],digest)
            self.assertEqual(row['path'],str(target));self.assertEqual(row['pool_id'],'STARTUP_LEAD')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        with closing(sqlite3.connect(cfg['shadow_db'])) as db:
            self.assertEqual(db.execute('SELECT pool_id,root FROM composition_material_pools').fetchone(),('old-template-pool',str(roots['STARTUP_LEAD'])))
            self.assertEqual(db.execute('SELECT template_json FROM shadow_profiles').fetchone()[0],'untouched template')


if __name__=='__main__':unittest.main()
