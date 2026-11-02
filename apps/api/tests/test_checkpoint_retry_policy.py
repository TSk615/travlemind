from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from travelmind_api.services.job_service import checkpoint_repair_exhausted


@pytest.mark.parametrize('message', [
    'Planner output still invalid after the single shared repair: schema_validation_failed (log: /app/storage/logs/jobs/private.jsonl)',
    'Planner repair budget exhausted',
])
def test_exhausted_checkpoint_cannot_be_advertised_as_recoverable(message):
    assert checkpoint_repair_exhausted(SimpleNamespace(error_message=message))


@pytest.mark.parametrize('message', [None, 'simulated worker loss', 'ReadTimeout', 'schema_validation_failed'])
def test_transient_and_first_parse_failures_are_not_globally_blocked(message):
    assert not checkpoint_repair_exhausted(SimpleNamespace(error_message=message))


def test_rejected_checkpoint_retry_does_not_create_job_or_debit_quota(client):
    from sqlalchemy import func, select
    from travelmind_api.core.database import SessionLocal
    from travelmind_api.db.models import GenerationQuota, JobRecord
    registration = client.post('/api/v1/auth/register', json={
        'name': 'Retry Tester', 'email': 'retry-test@example.com', 'password': 'fixture-password-123',
    })
    assert registration.status_code == 200
    user_id = registration.json()['data']['id']
    start = date.today() + timedelta(days=30)
    response = client.post('/api/v1/trips', json={
        'title': 'Retry fixture', 'origin': '广州', 'destination': '汕头',
        'start_date': start.isoformat(), 'end_date': (start + timedelta(days=4)).isoformat(),
        'budget': 5000, 'travelers': 2, 'interests': ['历史'],
        'accommodation_preference': '安静', 'pace': 'balanced', 'transport_mode': 'rail',
    })
    assert response.status_code == 200
    trip_id = response.json()['data']['id']
    with SessionLocal() as db:
        db.add(GenerationQuota(user_id=user_id, generation_limit=5, used=1))
        db.add(JobRecord(id='job_exhausted_checkpoint', type='trip.generate', status='failed',
                         owner_user_id=user_id, trip_id=trip_id,
                         payload_json={'trip_id': trip_id, 'resume_checkpoint': {'failed_role': 'itinerary_planner'}},
                         error_message='Planner output still invalid after the single shared repair: schema_validation_failed'))
        db.commit()
        count_before = db.scalar(select(func.count()).select_from(JobRecord))
    detail = client.get('/api/v1/jobs/job_exhausted_checkpoint')
    assert detail.status_code == 200 and detail.json()['data']['can_resume'] is False
    retry = client.post('/api/v1/jobs/job_exhausted_checkpoint/retry')
    assert retry.status_code == 409
    assert retry.json()['error']['code'] == 'job_resume_repair_exhausted'
    with SessionLocal() as db:
        assert db.get(GenerationQuota, user_id).used == 1
        assert db.scalar(select(func.count()).select_from(JobRecord)) == count_before
