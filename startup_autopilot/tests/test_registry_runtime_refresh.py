"""复现8502仍缓存旧Registry类时的依赖加载顺序；不读写生产库。"""
from pathlib import Path
import unittest
from unittest.mock import patch


class RegistryRuntimeRefreshTests(unittest.TestCase):
    def test_registry_is_in_full_revision_and_main_entry_upgrade_guard(self):
        from startup_autopilot import runtime_refresh as refresh
        self.assertIn('production_materials.store',refresh.ACCOUNT_MODULES)
        self.assertLess(refresh.ACCOUNT_MODULES.index('production_materials.config'),
                        refresh.ACCOUNT_MODULES.index('production_materials.store'))
        source=(Path(__file__).resolve().parents[2]/'benchmark/experiments/dino_july_web/app.py').read_text('utf-8')
        guard=source[source.index('from startup_autopilot import runtime_refresh as account_refresh'):]
        self.assertIn("'production_materials.store'",guard[:guard.index('account_refresh.ensure_shadow_revision()')])

    def test_old_registry_and_transitive_class_references_upgrade_in_dependency_order(self):
        import production_materials.store as registry
        import startup_autopilot.composition_catalog as catalog
        import startup_autopilot.template_store as templates
        import startup_autopilot.production as production
        import startup_autopilot.employee_ui as entry
        from startup_autopilot import runtime_refresh as refresh
        class OldRegistry(registry.Store):
            pass
        saved_revision=refresh._revision;reload=refresh.importlib.reload;loaded=[]
        def record(module):
            loaded.append(module.__name__);return reload(module)
        try:
            with patch.object(registry,'ProductionMaterialPoolRegistry',OldRegistry), \
                    patch.object(refresh,'ACCOUNT_MODULES',('production_materials.store',)), \
                    patch.object(refresh,'MODULES',('composition_catalog','template_store','production','employee_ui')), \
                    patch.object(refresh.importlib,'reload',side_effect=record):
                refresh._revision=None;refresh.ensure_shadow_revision()
                self.assertTrue(callable(getattr(registry.ProductionMaterialPoolRegistry,'startup_defaults',None)))
                self.assertTrue(callable(getattr(registry.ProductionMaterialPoolRegistry,'require_startup_pool',None)))
                self.assertIs(templates.CompositionCatalog,catalog.CompositionCatalog)
                self.assertIs(production.TemplateBuilderStore,templates.TemplateBuilderStore)
                self.assertIs(entry.ProductionStore,production.ProductionStore)
                self.assertEqual(loaded,['production_materials.store','startup_autopilot.composition_catalog',
                    'startup_autopilot.template_store','startup_autopilot.production','startup_autopilot.employee_ui'])
                refresh.ensure_shadow_revision();self.assertEqual(len(loaded),5)
        finally:refresh._revision=saved_revision


if __name__=='__main__':unittest.main()
