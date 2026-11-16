import json
import os
import tempfile
import unittest
from unittest.mock import patch
import realization_create as rc
import redmine

class CreationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.patch=patch.object(redmine,'DB',os.path.join(self.tmp.name,'test.db'));self.patch.start();self.addCleanup(self.patch.stop)
        self.parent={'id':42,'project':{'id':5},'status':{'id':1},'tracker':{'id':5},'updated_on':'v1','subject':'Test','children':[]}
        self.created={};self.writes=[]
    def request(self,path,params=None):
        if path=='/projects/realizace.json':return {'project':{'id':5}}
        if path=='/issues/42.json':return {'issue':self.parent}
        if path=='/issue_statuses.json':return {'issue_statuses':[{'id':1,'is_closed':False}]}
        if path=='/projects/realizace/memberships.json':return {'memberships':[{'user':{'id':7,'name':'honza'}},{'user':{'id':8,'name':'slavo'}}],'total_count':2}
        if path.startswith('/issues/'):return {'issue':self.created[int(path.split('/')[2].split('.')[0])]}
        raise AssertionError(path)
    def create(self,issue):
        self.writes.append(issue);iid=100+len(self.writes)
        self.created[iid]={'parent':{'id':issue['parent_issue_id']},'assigned_to':{'id':issue['assigned_to_id']},'subject':issue['subject'],'description':issue['description'],'project':{'id':issue['project_id']}}
        return iid
    def plan(self):
        c=rc.prepare(42,self.request)
        return {'request_id':'a'*32,'parent_id':42,'token':c['token'],'tasks':[{'subject':'Montáž – test','description':'Namontovat zařízení.','assignee_id':7},{'subject':'Data – test','description':'Připravit data.','assignee_id':8}]}
    def test_create_and_replay_is_idempotent(self):
        plan=self.plan();a=rc.create_batch(plan,self.request,redmine.connect,self.create);b=rc.create_batch(plan,self.request,redmine.connect,self.create)
        self.assertEqual(a,b);self.assertEqual(a['state'],'complete');self.assertEqual(len(self.writes),2);self.assertEqual(self.writes[0]['parent_issue_id'],42);self.assertEqual(self.writes[1]['assigned_to_id'],8)
    def test_unknown_write_never_retried(self):
        plan=self.plan()
        def uncertain(issue):self.writes.append(issue);raise RuntimeError('timeout')
        result=rc.create_batch(plan,self.request,redmine.connect,uncertain)
        self.assertEqual([t['state'] for t in result['tasks']],['unknown','pending'])
        self.assertEqual(rc.create_batch(plan,self.request,redmine.connect,self.create),result);self.assertEqual(len(self.writes),1)
    def test_partial_failure_records_success_and_stops(self):
        plan=self.plan()
        def second(issue):
            if self.writes:raise ValueError('HTTP 422')
            return self.create(issue)
        result=rc.create_batch(plan,self.request,redmine.connect,second)
        self.assertEqual([x['state'] for x in result['tasks']],['created','rejected']);self.assertEqual(len(self.writes),1)
    def test_stale_invalid_assignee_and_existing_are_rejected_without_writes(self):
        plan=self.plan();self.parent['updated_on']='v2'
        with self.assertRaisesRegex(ValueError,'změnila'):rc.create_batch(plan,self.request,redmine.connect,self.create)
        self.parent['updated_on']='v1';plan['tasks'][0]['assignee_id']=999
        with self.assertRaisesRegex(ValueError,'řešitele'):rc.create_batch(plan,self.request,redmine.connect,self.create)
        plan['tasks'][0]['assignee_id']=7;self.parent['children']=[{'id':5,'subject':'Montáž – test'}];plan['token']=rc.prepare(42,self.request)['token']
        with self.assertRaisesRegex(ValueError,'existuje'):rc.create_batch(plan,self.request,redmine.connect,self.create)
        self.assertFalse(self.writes)
    def test_missing_children_uses_verified_paged_query(self):
        del self.parent['children']
        def child_request(path,params=None):
            if path=='/issues.json':
                self.assertEqual(params['parent_id'],42);self.assertEqual(params['status_id'],'*')
                return {'issues':[{'id':9,'subject':'Existing','parent':{'id':42}}],'total_count':1}
            return self.request(path,params)
        self.assertEqual(rc.prepare(42,child_request)['children'],[{'id':9,'subject':'Existing'}])
        def ignored_filter(path,params=None):
            if path=='/issues.json':return {'issues':[{'id':9,'parent':{'id':99}}],'total_count':1}
            return self.request(path,params)
        with self.assertRaisesRegex(ValueError,'bezpečné'):rc.prepare(42,ignored_filter)

    def test_verification_failure_is_unknown_and_stops_batch(self):
        plan=self.plan()
        def cannot_verify(path,params=None):
            if path=='/issues/101.json':raise OSError('network')
            return self.request(path,params)
        result=rc.create_batch(plan,cannot_verify,redmine.connect,self.create)
        self.assertEqual(result['tasks'][0]['state'],'unknown');self.assertEqual(result['tasks'][0]['issue_id'],101)
        self.assertEqual(result['tasks'][1]['state'],'pending');self.assertEqual(len(self.writes),1)

    def test_open_status_may_omit_is_closed(self):
        def legacy_status(path,params=None):
            if path=='/issue_statuses.json':return {'issue_statuses':[{'id':1,'name':'Nový'}]}
            return self.request(path,params)
        self.assertEqual(rc.prepare(42,legacy_status)['id'],42)

    def test_closed_parent_and_missing_children_refused(self):
        self.parent['children']=None
        with self.assertRaisesRegex(ValueError,'dílčích'):rc.prepare(42,self.request)
        self.parent['children']=[]
        def closed(path,params=None):
            if path=='/issue_statuses.json':return {'issue_statuses':[{'id':1,'is_closed':True}]}
            return self.request(path,params)
        with self.assertRaisesRegex(ValueError,'otevřená'):rc.prepare(42,closed)

class ReadBoundaryTests(unittest.TestCase):
    def test_request_restricts_paths_and_disables_redirect(self):
        from io import BytesIO
        for path,params in [('https://bad.example/steal',{}),('/issues/1.json',{'include':'attachments'}),('/projects/secret.json',{})]:
            with self.subTest(path=path),patch.object(rc.urllib.request,'build_opener') as opener:
                with self.assertRaises(ValueError):rc.api_request('https://redmine.invalid','key',path,params)
                opener.assert_not_called()
        with patch.object(rc.urllib.request,'build_opener') as opener:
            opener.return_value.open.return_value=BytesIO(b'{"issue":{}}')
            self.assertEqual(rc.api_request('https://redmine.invalid','key','/issues/42.json',{'include':'children'}),{'issue':{}})
            handler=opener.call_args.args[0]
            self.assertIsNone(handler.redirect_request(None,None,302,None,None,'https://bad.example'))

class HttpBoundaryTests(unittest.TestCase):
    def test_missing_or_foreign_origin_never_dispatches_write(self):
        import threading, urllib.request, urllib.error
        from http.server import ThreadingHTTPServer
        server=ThreadingHTTPServer(('127.0.0.1',0),redmine.Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            url=f'http://127.0.0.1:{server.server_port}/api/realization-create'
            with patch.object(rc,'create_batch') as create:
                for headers in ({'Content-Type':'application/json'}, {'Content-Type':'application/json','Origin':'https://invalid.example'}):
                    req=urllib.request.Request(url,data=b'{}',headers=headers,method='POST')
                    with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(req)
                    self.assertEqual(caught.exception.code,403)
                create.assert_not_called()
        finally:
            server.shutdown();server.server_close();worker.join()

if __name__=='__main__':unittest.main()
