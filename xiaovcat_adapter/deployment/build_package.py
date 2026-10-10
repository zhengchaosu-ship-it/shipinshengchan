"""精确Python源码依赖闭包的机械打包；不扫描/复制素材、数据库、配置凭证或整个项目。"""
import ast
import importlib.util
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent


def build():
    seeds=['xiaovcat_adapter.lan_publish_worker','xiaovcat_adapter.desktop_ui_lane',
           'xiaovcat_adapter.local_ui_publisher','xiaovcat_adapter.desktop_worker.ready_actions',
           'xiaovcat_adapter.group_sync']
    seen={};pending=list(seeds)
    def add(module):
        if module and module not in seen:pending.append(module)
    while pending:
        module=pending.pop()
        if module in seen:continue
        path=ROOT/Path(*module.split('.')).with_suffix('.py')
        if not path.is_file():
            path=ROOT/Path(*module.split('.'))/'__init__.py'
        if not path.is_file():continue
        seen[module]=path
        parts=module.split('.')
        for i in range(1,len(parts)):add('.'.join(parts[:i]))
        package=module if path.name=='__init__.py' else module.rpartition('.')[0]
        for node in ast.walk(ast.parse(path.read_text('utf-8-sig'))):
            if isinstance(node,ast.Import):
                for item in node.names:add(item.name)
            elif isinstance(node,ast.ImportFrom):
                try:base=importlib.util.resolve_name('.'*node.level+(node.module or ''),package) if node.level else node.module
                except (ImportError,ValueError):continue
                add(base)
                for item in node.names:
                    if item.name!='*':add((base+'.' if base else '')+item.name)
    output=ROOT/'xiaovcat_adapter/runtime/lan_publish_2060s/worker_runtime.zip'
    output.parent.mkdir(parents=True,exist_ok=True)
    # 根入口使用专门部署模板，不携带服务器旧入口。
    seen.pop('xiaovcat_publish_worker',None)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in seen.values():archive.write(path,path.relative_to(ROOT).as_posix())
        archive.write(HERE/'publish_entry.py','xiaovcat_publish_worker.py')
        for source,target in [('worker.2060s.json','worker.config.json'),('START_JOB3_UI_DRY_RUN.cmd','START_JOB3_UI_DRY_RUN.cmd'),
                              ('START_JOB3_FIRST_REAL_ACCEPTANCE.cmd','START_JOB3_FIRST_REAL_ACCEPTANCE.cmd'),
                              ('README_2060S.txt','README.txt')]:
            archive.write(HERE/source,target)
        archive.writestr('xiaovcat_adapter/config.json',json.dumps(dict(real_publish_enabled=False,executable_path='D:/小V猫/小V猫.exe',
            process_name='小V猫.exe',operations_db='UNUSED_NO_LOCAL_BUSINESS_DB'),ensure_ascii=False))
        archive.writestr('config.json',json.dumps(dict(paths=dict(python_executable='D:/JianyingRenderWorker/venv/Scripts/python.exe',
            ffprobe_executable='D:/JianyingRenderWorker/Tools/FFmpeg/ffmpeg-9.0.2-essentials_build/bin/ffprobe.exe'))))
    names=zipfile.ZipFile(output).namelist()
    if any(name.lower().endswith(('.db','.dpapi','.mp4','.pem','.key')) for name in names):raise RuntimeError('PACKAGE_SENSITIVE_FILE_FORBIDDEN')
    print(json.dumps(dict(package=str(output),source_files=len(seen),files=len(names),bytes=output.stat().st_size),ensure_ascii=False))


if __name__=='__main__':build()
