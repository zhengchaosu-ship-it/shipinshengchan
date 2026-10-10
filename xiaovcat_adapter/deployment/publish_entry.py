"""2060S部署根入口；所有模式均走LAN Worker，无本地业务库。"""
import re

def safe_code(error):
    match=re.match(r'[A-Z][A-Z0-9_]+',str(error))
    return match.group() if match else 'LOCAL_WORKER_ERROR'

if __name__=='__main__':
    import sys
    if '--user-real-once' in sys.argv or '--user-ui-dry-run' in sys.argv:
        print('JOB_CANCELLED')
        raise SystemExit(20)
    from xiaovcat_adapter.lan_publish_worker import main
    main()
