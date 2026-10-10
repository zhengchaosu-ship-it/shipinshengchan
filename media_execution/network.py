"""只检查发布网络；不修改代理、不绕过平台验证。"""
import os
import urllib.request
import json
import time

_route_cache = None


def inspect_runtime_network():
    """只读检查本机物理默认路由和活动虚拟网卡；不改代理或VPN。"""
    global _route_cache
    from yixiaoer_adapter.cli_runner import run_hidden
    now=time.monotonic()
    if _route_cache is None or now-_route_cache[0]>5:
        command="[pscustomobject]@{adapters=@(Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object ifIndex,HardwareInterface);routes=@(Get-NetRoute -AddressFamily IPv4 | Where-Object {$_.DestinationPrefix -in @('0.0.0.0/0','0.0.0.0/1','128.0.0.0/1')} | Select-Object InterfaceIndex,DestinationPrefix)} | ConvertTo-Json -Compress -Depth 4"
        try:
            result=run_hidden(['powershell.exe','-NoProfile','-Command',command],capture_output=True,timeout=15)
            if result.returncode:raise ValueError('ROUTE_READ_FAILED')
            details=json.loads(result.stdout)
            adapters=details['adapters'];routes=details['routes']
            physical={r['ifIndex'] for r in adapters if r['HardwareInterface'] is True}
            direct=bool(routes and adapters and all(r['HardwareInterface'] is True for r in adapters)
                and all(r['InterfaceIndex'] in physical and r['DestinationPrefix']=='0.0.0.0/0' for r in routes))
            _route_cache=(now,details,'DIRECT_CONFIRMED' if direct else 'UNKNOWN')
        except Exception as error:
            _route_cache=(now,{'error':type(error).__name__},'UNKNOWN')
    result=inspect_publish_network(vpn_status=_route_cache[2])
    result['route_evidence']=_route_cache[1]
    return result


def require_runtime_network():
    from .coordinator import ExecutionFailure
    result=inspect_runtime_network()
    if result['state']!='ONLINE':
        raise ExecutionFailure('INFRA_LEVEL','PUBLISH_NETWORK_ATTENTION',evidence=result)
    return result


def inspect_publish_network(*, environ=None, proxies=None, vpn_status='UNKNOWN'):
    environ = os.environ if environ is None else environ
    proxies = urllib.request.getproxies() if proxies is None else proxies
    reasons = []
    if any(str(environ.get(key,'')).strip() for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy')):
        reasons.append('PROXY_ENVIRONMENT_PRESENT')
    if any(value for key,value in proxies.items() if key.lower()!='no'):
        reasons.append('SYSTEM_PROXY_PRESENT')
    if vpn_status != 'DIRECT_CONFIRMED':
        reasons.append('VPN_OR_DIRECT_ROUTE_NOT_CONFIRMED')
    return {'state':'PUBLISH_NETWORK_ATTENTION' if reasons else 'ONLINE','reasons':reasons,
            'vpn_status':vpn_status,'proxy_values_redacted':True}


def require_publish_network(**kwargs):
    from .coordinator import ExecutionFailure
    result = inspect_publish_network(**kwargs)
    if result['state']!='ONLINE':
        raise ExecutionFailure('INFRA_LEVEL','PUBLISH_NETWORK_ATTENTION',evidence=result)
    return result
