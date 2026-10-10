"""Rollback command ordering and failure containment without touching a deployment."""

import json
from contextlib import nullcontext

import pytest

from scripts import rollback_release as release

IMAGE = 'sha256:' + 'a'*64


def fixture_runner(monkeypatch, *, labels=None, fail_start=False):
    calls = []
    def run(args, env):
        calls.append((args, env.get('AGENT_IMAGE')))
        if args[:2] == ['image', 'inspect']:
            return json.dumps([{'Config':{'Labels':labels or {}}}])
        if 'up' in args and fail_start:
            raise RuntimeError('Deployment startup failed')
        return ''
    monkeypatch.setattr(release, 'run', run)
    return calls


def test_unsafe_old_image_is_rejected_before_modifying_deployment(monkeypatch):
    calls = fixture_runner(monkeypatch)
    with pytest.raises(ValueError, match='safety contract'):
        release.rollback(env_file='unused.env', previous_image=IMAGE, base_url='http://unused')
    assert len(calls) == 1


def test_mutable_tag_is_rejected_without_docker_calls(monkeypatch):
    calls = fixture_runner(monkeypatch)
    with pytest.raises(ValueError, match='immutable'):
        release.rollback(env_file='unused.env', previous_image='app:latest', base_url='http://unused')
    assert not calls


def test_compatible_rollback_closes_before_switching_and_keeps_closed(monkeypatch):
    labels = {'agent.schema':'0004', 'agent.safety-contract':'2026-10-10'}
    calls = fixture_runner(monkeypatch, labels=labels)
    monkeypatch.setattr(release, 'urlopen', lambda *_a, **_k: nullcontext(type('Response', (), {'status':200})()))
    release.rollback(env_file='unused.env', previous_image=IMAGE, base_url='http://unused')
    stop_command = next(i for i, (args, _) in enumerate(calls) if 'backend.scripts.emergency_stop' in args)
    switch_command = next(i for i, (args, _) in enumerate(calls) if 'up' in args)
    assert stop_command < switch_command
    assert calls[switch_command][1] == IMAGE
    assert calls[-1][0][-1] == '--check'
    assert not any('downgrade' in args or '--volumes' in args for args, _ in calls)


def test_failed_rollback_stops_api_instead_of_leaving_broken_entry(monkeypatch):
    calls = fixture_runner(monkeypatch, labels={'agent.schema':'0004', 'agent.safety-contract':'2026-10-10'}, fail_start=True)
    with pytest.raises(RuntimeError, match='startup failed'):
        release.rollback(env_file='unused.env', previous_image=IMAGE, base_url='http://unused')
    assert calls[-1][0][-2:] == ['stop', 'api']
