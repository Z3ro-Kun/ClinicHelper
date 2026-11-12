import pytest
from pydantic import ValidationError
from app.models import ClinicalField, CaseInput
from app.reconciliation import reconcile
from app.main import app, coordinator, create_case, resolve, readiness, history, Resolution
from fastapi import HTTPException


def field(value, doc='summary', status='present'):
    return dict(value=value, status=status, sources=[dict(document_id=doc, line=1)])


def sample():
    def document(doc, frequency):
        return dict(document_id=doc, medicines=[dict(name=field('Metoprolol', doc),
            dose=field('25 mg', doc), frequency=field(frequency, doc), duration=field(None, doc, 'missing'))],
            follow_up=[field('7 days', doc)], warning_signs=[field('Supplied synthetic warning', doc)],
            unreadable_regions=[])
    return dict(patient_alias='Synthetic R', summary=document('summary', 'twice daily'),
                prescription=document('slip', 'once daily'))


def test_missing_and_unreadable_are_separate():
    data = sample()
    data['prescription']['medicines'][0]['dose'] = field(None, 'slip', 'unreadable')
    flags = reconcile(CaseInput.model_validate(data))
    assert {'missing', 'unreadable', 'conflict'} <= {f['kind'] for f in flags}


def test_unknown_value_cannot_be_guessed():
    with pytest.raises(ValidationError):
        ClinicalField.model_validate(field('25 mg', status='missing'))


def test_present_value_requires_evidence():
    with pytest.raises(ValidationError):
        ClinicalField(value='25 mg', status='present', sources=[])


def test_omitted_status_is_invalid():
    with pytest.raises(ValidationError):
        ClinicalField.model_validate({'value': None, 'sources': []})


def test_region_without_recognized_medicine_survives():
    data = sample()
    data['prescription']['unreadable_regions'] = [dict(document_id='slip', line=3)]
    assert any(f['path'] == 'slip.regions.0' for f in reconcile(CaseInput.model_validate(data)))


def test_auth_audit_and_concurrency(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_PATH', str(tmp_path / 'test.db'))
    monkeypatch.setenv('COORDINATOR_TOKEN', 'test-secret')
    with pytest.raises(HTTPException) as denied:
        coordinator('')
    assert denied.value.status_code == 401
    actor = coordinator('Bearer test-secret')
    case = create_case(CaseInput.model_validate(sample()), actor)
    decision = dict(action='escalate', value=None, reason='Needs prescriber clarification',
                    evidence='Synthetic source reviewed', expected_revision=1)
    resolve(case['id'], '1', Resolution.model_validate(decision), actor)
    with pytest.raises(HTTPException) as stale:
        resolve(case['id'], '1', Resolution.model_validate(decision), actor)
    assert stale.value.status_code == 409
    ready = readiness(case['id'], actor)
    assert not ready['release_allowed'] and ready['blocking_flags']
    assert len(history(case['id'], actor)) == 2
