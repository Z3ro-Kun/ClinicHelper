import hmac
import os
from uuid import uuid4
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import Field
from app.models import CaseInput, Decision, StrictModel
from app.reconciliation import reconcile
from app.store import transaction, get, save, audit

app = FastAPI(title='ClinicHelper', version='0.1.0')


def coordinator(authorization: str = Header(default='')):
    token = os.getenv('COORDINATOR_TOKEN', '')
    if not token:
        raise HTTPException(503, 'Coordinator authentication is not configured')
    if not hmac.compare_digest(authorization, 'Bearer ' + token):
        raise HTTPException(401, 'Invalid credentials')
    return 'configured_coordinator'


def require_case(db, case_id):
    case = get(db, case_id)
    if case is None:
        raise HTTPException(404, 'Case not found')
    return case


@app.get('/', response_class=HTMLResponse)
def home():
    return '<h1>ClinicHelper</h1><p>Clinical review backend — development foundation.</p><p><a href="/docs">Open interactive API</a></p><p>Synthetic cases only. Nexus and family release are not enabled yet.</p>'


@app.get('/health')
def health():
    return {'status': 'ok', 'nexus_configured': bool(os.getenv('NEXUS_API_KEY'))}


@app.post('/cases', status_code=201)
def create_case(body: CaseInput, actor=Depends(coordinator)):
    case = {'id': str(uuid4()), 'input': body.model_dump(), 'flags': reconcile(body),
            'status': 'review_required', 'revision': 1, 'questions': []}
    with transaction() as db:
        save(db, case)
        audit(db, case['id'], actor, 'case_created', {'revision': 1})
    return case


@app.get('/cases/{case_id}')
def read_case(case_id: str, actor=Depends(coordinator)):
    with transaction() as db:
        return require_case(db, case_id)


class Resolution(Decision):
    expected_revision: int = Field(ge=1)


@app.post('/cases/{case_id}/flags/{flag_id}/resolve')
def resolve(case_id: str, flag_id: str, body: Resolution, actor=Depends(coordinator)):
    with transaction() as db:
        case = require_case(db, case_id)
        if body.expected_revision != case['revision']:
            raise HTTPException(409, 'Case changed; reload before deciding')
        flag = next((f for f in case['flags'] if f['id'] == flag_id), None)
        if not flag:
            raise HTTPException(404, 'Flag not found')
        flag['decision'] = body.model_dump()
        flag['status'] = 'escalated' if body.action == 'escalate' else 'resolved'
        case['revision'] += 1
        case['status'] = 'review_required'
        save(db, case)
        audit(db, case_id, actor, 'flag_decision', {'flag_id': flag_id, **body.model_dump()})
        return case


@app.get('/cases/{case_id}/readiness')
def readiness(case_id: str, actor=Depends(coordinator)):
    with transaction() as db:
        case = require_case(db, case_id)
        blocked = [f['id'] for f in case['flags'] if f['status'] != 'resolved']
        return {'blocking_flags': blocked, 'reconciliation_complete': not blocked,
                'release_allowed': False, 'reason': 'Final plan review and release are not implemented'}


@app.get('/cases/{case_id}/audit')
def history(case_id: str, actor=Depends(coordinator)):
    with transaction() as db:
        require_case(db, case_id)
        return [dict(row) for row in db.execute('SELECT * FROM audit WHERE case_id=? ORDER BY id', (case_id,))]
