"""SYSTEM计划任务错误可见入口；采集失败只写监督层证据。"""
from logging.handlers import RotatingFileHandler
import logging
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    folder=root/'runtime/maintenance_watchdog'; folder.mkdir(parents=True,exist_ok=True)
    logger=logging.getLogger('collector'); logger.setLevel(logging.INFO)
    handler=RotatingFileHandler(folder/'collector.log',maxBytes=5*1024**2,backupCount=3,encoding='utf-8')
    logger.addHandler(handler)
    try:
        logger.info('START %s',sys.argv[1:])
        from server_maintenance.watchdog import main as run
        run(); logger.info('COMPLETE')
        return 0
    except Exception:
        logger.exception('MAINTENANCE_WATCHDOG_UNAVAILABLE; production unchanged')
        return 1
    finally:handler.close()


if __name__=='__main__':raise SystemExit(main())
