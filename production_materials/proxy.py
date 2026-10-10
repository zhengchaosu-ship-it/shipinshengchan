"""8502同源、固定回环后端的素材代理；不接受客户端指定目标或服务器文件路径。"""
import asyncio
import ipaddress
import json
from urllib.parse import urlsplit

import httpx

from .config import settings

PREFIX = '/production-materials'
RESPONSE_HEADERS = {'content-type', 'content-length', 'content-range', 'accept-ranges',
                    'cache-control', 'x-content-type-options', 'content-security-policy'}


class MaterialProxy:
    def __init__(self, config=None, *, frontend_port=8502):
        self.config = config or settings()
        self.frontend_port = frontend_port
        self.backend = 'http://127.0.0.1:'+str(self.config['port'])
        self.slots = asyncio.Semaphore(12)

    async def error(self, send, status, code):
        body = json.dumps({'error':code},ensure_ascii=False).encode()
        await send({'type':'http.response.start','status':status,'headers':[
            (b'content-type',b'application/json; charset=utf-8'),(b'cache-control',b'no-store'),
            (b'content-length',str(len(body)).encode()),(b'x-content-type-options',b'nosniff')]})
        await send({'type':'http.response.body','body':body})

    def guard(self, scope, headers):
        peer = ipaddress.ip_address(scope['client'][0])
        if isinstance(peer,ipaddress.IPv6Address) and peer.ipv4_mapped:
            peer = peer.ipv4_mapped
        if not any(peer in ipaddress.ip_network(n) for n in self.config['trusted_networks']):
            return 403,'LAN_ONLY'
        host = headers.get('host','').lower()
        parsed = urlsplit('http://'+host)
        if parsed.hostname not in [h.lower() for h in self.config['allowed_hosts']] or parsed.port != self.frontend_port:
            return 403,'INVALID_HOST'
        if any(h in headers for h in ('forwarded','x-forwarded-for','x-real-ip','x-forwarded-host')):
            return 403,'DIRECT_LAN_CONNECTION_REQUIRED'
        if scope['method'] not in ('GET','POST','PUT'):
            return 405,'METHOD_NOT_ALLOWED'
        if headers.get('transfer-encoding'):
            return 411,'USE_BOUNDED_CHUNKS'
        if scope['method'] != 'GET' and headers.get('origin') != scope['scheme']+'://'+host:
            return 403,'SAME_ORIGIN_REQUIRED'
        return None

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            if scope['type']=='websocket':
                await send({'type':'websocket.close','code':1008})
            return
        headers = {k.decode('latin1').lower():v.decode('latin1') for k,v in scope['headers']}
        try:
            blocked = self.guard(scope,headers)
        except (ValueError,TypeError,KeyError):
            blocked = (403,'INVALID_REQUEST_ORIGIN')
        if blocked:
            return await self.error(send,*blocked)
        path = scope['path']
        root = scope.get('root_path','')
        if root and path.startswith(root):
            path = path[len(root):] or '/'
        limit = self.config.get('chunk_bytes',4*1024**2) if scope['method']=='PUT' else 256*1024
        try:
            length = int(headers.get('content-length','0'))
        except ValueError:
            return await self.error(send,400,'INVALID_CONTENT_LENGTH')
        if length < 0 or length > limit or scope['method']!='GET' and not length:
            return await self.error(send,413,'REQUEST_TOO_LARGE')
        # 只缓冲一个有界分片，不把完整大视频装入8502内存。
        body = bytearray()
        try:
            while True:
                message = await asyncio.wait_for(receive(),timeout=60)
                if message['type']=='http.disconnect':
                    return
                body.extend(message.get('body',b''))
                if len(body)>length or len(body)>limit:
                    return await self.error(send,413,'REQUEST_TOO_LARGE')
                if not message.get('more_body'):
                    break
        except TimeoutError:
            return await self.error(send,408,'INCOMPLETE_REQUEST')
        if len(body)!=length:
            return await self.error(send,400,'INCOMPLETE_REQUEST')
        forwarded = {k:v for k,v in headers.items() if k in ('content-type','range','x-upload-token','x-chunk-sha256')}
        if scope['method']!='GET':
            # 只有上述LAN/Host/Origin全部通过后才转换为后端同源请求。
            forwarded['origin'] = self.backend
        url = self.backend+path
        if scope.get('query_string'):
            url += '?'+scope['query_string'].decode('ascii')
        response = None
        started = False
        async with self.slots:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120,connect=3),trust_env=False,follow_redirects=False) as client:
                try:
                    request = client.build_request(scope['method'],url,headers=forwarded,content=bytes(body))
                    response = await client.send(request,stream=True)
                    # JSON很小，读完再返回状态；后端早拒绝时连接重置也能给员工可恢复提示。
                    if response.headers.get('content-type','').startswith('application/json'):
                        chunks = bytearray()
                        async for block in response.aiter_raw(64*1024):
                            chunks.extend(block)
                            if len(chunks)>1024**2:
                                raise httpx.ReadError('MATERIAL_JSON_RESPONSE_TOO_LARGE')
                        await send({'type':'http.response.start','status':response.status_code,
                                    'headers':[(k.encode('latin1'),v.encode('latin1')) for k,v in response.headers.items() if k in RESPONSE_HEADERS]})
                        started = True
                        await send({'type':'http.response.body','body':bytes(chunks)})
                        return
                    await send({'type':'http.response.start','status':response.status_code,
                                'headers':[(k.encode('latin1'),v.encode('latin1')) for k,v in response.headers.items() if k in RESPONSE_HEADERS]})
                    started = True
                    async for block in response.aiter_raw(64*1024):
                        await send({'type':'http.response.body','body':block,'more_body':True})
                    await send({'type':'http.response.body','body':b''})
                except httpx.HTTPError:
                    if not started:
                        await self.error(send,503,'MATERIAL_SERVICE_UNAVAILABLE')
                    else:
                        raise
                finally:
                    if response is not None:
                        await response.aclose()
