"""挂在既有LAN认证接口之下；Worker没有新增Job、解门或重新排期权限。"""
class ExecutionAPI:
    def __init__(self, control, worker_ids):
        self.control,self.worker_ids = control,set(worker_ids)

    def dispatch(self, action, value):
        worker = value.get('worker_id')
        if worker not in self.worker_ids:
            raise PermissionError('MEDIA_WORKER_NOT_ALLOWED')
        token = value.get('lease_token')
        if action in ('render-complete','publish-complete','reconciliation-result') and hasattr(self.control,'prior_receipt'):
            prior=self.control.prior_receipt(worker,token,action,value['output' if action=='render-complete' else 'response'])
            if prior:
                return prior
        if action=='worker-health':
            return self.control.report_worker(worker,value['details'])
        if action=='archive-pending':
            return self.control.archive_pending(worker)
        if action=='archive-result':
            return self.control.archive_report(worker,value['content_id'],value.get('receipt'),value.get('error'))
        if action=='claim':
            return self.control.claim(worker)
        if action=='claim-reconciliation':
            return self.control.claim_reconciliation(worker)
        if action=='snapshot':
            return self.control.snapshot(worker)
        if action=='heartbeat':
            self.control.heartbeat(worker,token)
            return {'saved':True}
        if action=='stage':
            self.control.stage(worker,token,value['stage'])
            return {'saved':True}
        if action=='input':
            return self.control.publish_input(worker,token)
        if action=='submit-intent':
            return self.control.reserve_submit(worker,token,value['intent'])
        if action=='render-complete':
            self.control.complete_render(worker,token,value['output'])
            return {'saved':True}
        if action=='publish-complete':
            self.control.complete_publish(worker,token,value['response'])
            return {'saved':True}
        if action=='reconciliation-result':
            self.control.record_reconciliation(worker,token,value['response'])
            return {'saved':True}
        if action=='reconciliation-error':
            self.control.reconciliation_error(worker,token,value['error'])
            return {'saved':True}
        if action=='failed':
            return self.control.fail(worker,token,value['domain'],value['reason'],gate=value.get('gate'),evidence=value.get('evidence'))
        if action=='recover':
            return self.control.recovery(worker,executor_quiescent=value.get('executor_quiescent'),journal=value.get('journal'))
        raise PermissionError('MEDIA_WORKER_ACTION_NOT_ALLOWED')


class RemoteControlPlane:
    def __init__(self, transport):
        self.transport = transport

    def call(self, action, worker, token=None, **values):
        # Submit intent/回执不作透明重试；失去回复由journal恢复，不重放外部操作。
        prefix=self.transport.config.get('execution_api_prefix','/media-execution/') if hasattr(self.transport,'config') else '/media-execution/'
        if prefix not in ('/media-execution/','/media-acceptance/'):
            raise PermissionError('UNKNOWN_EXECUTION_API')
        return self.transport.call(prefix+action,
            dict(worker_id=worker,lease_token=token,**values),attempts=1)

    def claim(self, worker):
        return self.call('claim',worker)

    def claim_reconciliation(self, worker):
        return self.call('claim-reconciliation',worker)

    def record_reconciliation(self, worker, token, response):
        return self.call('reconciliation-result',worker,token,response=response)

    def reconciliation_error(self, worker, token, error):
        return self.call('reconciliation-error',worker,token,error=error)

    def heartbeat(self, worker, token):
        return self.call('heartbeat',worker,token)

    def stage(self, worker, token, stage):
        return self.call('stage',worker,token,stage=stage)

    def publish_input(self, worker, token):
        return self.call('input',worker,token)

    def reserve_submit(self, worker, token, intent):
        return self.call('submit-intent',worker,token,intent=intent)

    def complete_render(self, worker, token, output):
        return self.call('render-complete',worker,token,output=output)

    def complete_publish(self, worker, token, response):
        return self.call('publish-complete',worker,token,response=response)

    def fail(self, worker, token, domain, reason, **kwargs):
        return self.call('failed',worker,token,domain=domain,reason=reason,**kwargs)

    def recovery(self, worker, **kwargs):
        return self.call('recover',worker,**kwargs)

    def snapshot(self, worker):
        return self.call('snapshot',worker)

    def report_worker(self, worker, details):
        return self.call('worker-health',worker,details=details)

    def archive_pending(self, worker):
        return self.call('archive-pending',worker)

    def archive_report(self, worker, content_id, receipt=None, error=None):
        return self.call('archive-result',worker,content_id=content_id,receipt=receipt,error=error)
