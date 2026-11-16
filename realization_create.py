"""Controlled creation of realization subtasks with a durable no-retry journal."""
import hashlib
import json
import re
import threading
import urllib.error
import urllib.request
import urllib.parse

LOCK = threading.Lock()


def api_request(base, key, path, params=None):
    """Read only the endpoints needed for this workflow, without redirects."""
    params = params or {}
    allowed = {'/projects/realizace.json':set(), '/issue_statuses.json':set(),
               '/projects/realizace/memberships.json':{'limit','offset'},
               '/issues.json':{'project_id','parent_id','status_id','limit','offset'}}
    if re.fullmatch(r'/issues/[1-9][0-9]{0,11}\.json',path):
        permitted={'include'}
        if params.get('include') not in (None,'children'): raise ValueError('Nepovolený požadavek.')
    elif path in allowed: permitted=allowed[path]
    else: raise ValueError('Nepovolený požadavek.')
    if set(params)-permitted: raise ValueError('Nepovolené parametry.')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs): return None
    url=base+path+('?' + urllib.parse.urlencode(params) if params else '')
    req=urllib.request.Request(url,headers={'X-Redmine-API-Key':key,'Accept':'application/json'})
    with urllib.request.build_opener(NoRedirect()).open(req,timeout=30) as response:
        return json.load(response)


def prepare(parent_id, request):
    if type(parent_id) is not int or parent_id <= 0:
        raise ValueError('Zadejte platné číslo realizace.')
    project = request('/projects/realizace.json')['project']
    parent = request(f'/issues/{parent_id}.json', {'include': 'children'})['issue']
    if parent.get('project', {}).get('id') != project.get('id') or not project.get('id'):
        raise ValueError('Nadřazený úkol nepatří do projektu Realizace.')
    statuses = request('/issue_statuses.json')['issue_statuses']
    status = next((s for s in statuses if s.get('id') == parent.get('status', {}).get('id')), None)
    # Older Redmine omits is_closed for open states and returns true for closed ones.
    if not status or status.get('is_closed', False) is not False:
        raise ValueError('Realizace není otevřená nebo nelze ověřit její stav.')
    if 'children' not in parent:
        # Some Redmine versions omit an empty association. Query direct children,
        # including closed issues, and reject a server that ignores the filter.
        children, offset = [], 0
        while True:
            page = request('/issues.json', {'project_id':project['id'], 'parent_id':parent_id, 'status_id':'*', 'limit':100, 'offset':offset})
            batch, total = page.get('issues'), page.get('total_count')
            if not isinstance(batch,list) or type(total) is not int or total < 0:
                raise ValueError('Redmine neposkytl úplný seznam dílčích úkolů.')
            if any(item.get('parent',{}).get('id') != parent_id for item in batch):
                raise ValueError('Redmine nepodporuje bezpečné ověření dílčích úkolů.')
            children.extend(batch);offset += len(batch)
            if offset >= total: break
            if not batch or offset > 10000: raise ValueError('Seznam dílčích úkolů je neúplný.')
        parent = {**parent, 'children':children}
    if not isinstance(parent.get('children'), list):
        raise ValueError('Redmine neposkytl seznam dílčích úkolů; nelze bezpečně ověřit duplicity.')
    if not parent.get('updated_on') or not parent.get('tracker', {}).get('id'):
        raise ValueError('Redmine neposkytl potřebné údaje realizace.')
    members, offset = [], 0
    while True:
        payload = request('/projects/realizace/memberships.json', {'limit': 100, 'offset': offset})
        batch, total = payload.get('memberships'), payload.get('total_count')
        if not isinstance(batch,list) or type(total) is not int or total < 0:
            raise ValueError('Redmine neposkytl úplný seznam řešitelů.')
        members.extend(m['user'] for m in batch if m.get('user') and type(m['user'].get('id')) is int)
        offset += len(batch)
        if offset >= total: break
        if not batch or offset > 10000: raise ValueError('Seznam řešitelů je neúplný.')
    members = sorted({m['id']: {'id':m['id'], 'name':m.get('name', '')} for m in members}.values(),key=lambda m:m['name'].casefold())
    children=[{'id':c.get('id'),'subject':c.get('subject','')} for c in parent['children']]
    token=hashlib.sha256(json.dumps({'id':parent_id,'updated':parent['updated_on'],'children':children},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {'id':parent_id,'subject':parent.get('subject',''),'updated_on':parent['updated_on'], 'token':token,
            'project_id':project['id'],'tracker_id':parent['tracker']['id'],'members':members,'children':children}


def create_http(base, key, issue):
    body=json.dumps({'issue':issue},ensure_ascii=False).encode('utf-8')
    req=urllib.request.Request(base+'/issues.json',data=body,method='POST',headers={'X-Redmine-API-Key':key,'Content-Type':'application/json','Accept':'application/json'})
    # No redirects: a credentialed POST must never be followed to another location.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs): return None
    try:
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=30) as res:
            return json.load(res)['issue']['id']
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500:
            raise ValueError(f'Redmine úkol odmítl (HTTP {exc.code}).') from None
        raise RuntimeError('Výsledek zápisu není znám.') from None
    except Exception:
        raise RuntimeError('Výsledek zápisu není znám.') from None


def create_batch(plan, request, connect, create):
    if not isinstance(plan,dict) or not re.fullmatch(r'[0-9a-f]{32}',str(plan.get('request_id',''))):
        raise ValueError('Neplatné ID požadavku.')
    rid=plan['request_id']
    with LOCK:
        with connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS realization_jobs (id TEXT PRIMARY KEY, plan_hash TEXT NOT NULL, result TEXT NOT NULL)')
            row=db.execute('SELECT plan_hash,result FROM realization_jobs WHERE id=?',(rid,)).fetchone()
        digest=hashlib.sha256(json.dumps(plan,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if row:
            if row[0] != digest: raise ValueError('Požadavek byl změněn; založení nelze zopakovat.')
            return json.loads(row[1])
        parent=prepare(plan.get('parent_id'),request)
        if parent['token'] != plan.get('token'):
            raise ValueError('Realizace se změnila. Načtěte ji znovu.')
        items=plan.get('tasks')
        if not isinstance(items,list) or not 1 <= len(items) <= 20: raise ValueError('Vyberte 1 až 20 úkolů.')
        ids={m['id'] for m in parent['members']}; existing={c['subject'].strip().casefold() for c in parent['children']}
        normalized=[]
        for item in items:
            if not isinstance(item,dict) or not isinstance(item.get('subject'),str) or not isinstance(item.get('description'),str) or len(item['description']) > 1000 or type(item.get('assignee_id')) is not int or item['assignee_id'] not in ids:
                raise ValueError('U každého úkolu vyberte platného řešitele projektu.')
            subject=' '.join(item['subject'].split())
            if not 1 <= len(subject) <= 255 or subject.casefold() in existing: raise ValueError('Název úkolu je neplatný nebo již existuje mezi dílčími úkoly.')
            existing.add(subject.casefold());normalized.append({'subject':subject,'assignee_id':item['assignee_id'],'description':item['description'].strip(),'state':'pending'})
        result={'request_id':rid,'parent_id':parent['id'],'state':'running','tasks':normalized}
        def save(insert=False):
            with connect() as db:
                if insert: db.execute('INSERT INTO realization_jobs (id,plan_hash,result) VALUES (?,?,?)',(rid,digest,json.dumps(result,ensure_ascii=False)))
                else: db.execute('UPDATE realization_jobs SET result=? WHERE id=?',(json.dumps(result,ensure_ascii=False),rid))
        save(True)
        for task in result['tasks']:
            task['state']='sending';save()
            issue={'project_id':parent['project_id'],'tracker_id':parent['tracker_id'],'parent_issue_id':parent['id'],'subject':task['subject'],'description':task['description'],'assigned_to_id':task['assignee_id']}
            try:
                created_id=create(issue)
                if type(created_id) is not int or created_id <= 0: raise RuntimeError('Redmine nevrátil ID úkolu.')
                task['issue_id']=created_id
                verified=request(f'/issues/{created_id}.json')['issue']
                if verified.get('parent',{}).get('id') != parent['id'] or verified.get('assigned_to',{}).get('id') != task['assignee_id'] or verified.get('subject') != task['subject'] or verified.get('project',{}).get('id') != parent['project_id'] or verified.get('description','') != task['description']:
                    raise RuntimeError('Založený úkol se nepodařilo ověřit.')
                task['state']='created';save()
            except Exception as exc:
                task['state']='rejected' if isinstance(exc,ValueError) and 'issue_id' not in task else 'unknown'
                task['error']=str(exc)[:200];result['state']='stopped';save();return result
        result['state']='complete';save();return result
