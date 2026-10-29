from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import rfc8785

from pals_agent.geometry_input import GeometryInputError, GeometryProblem
from pals_agent.material_context import proposition_question

_FIXTURE = Path(__file__).parents[2] / 'testdata/synthetic-geometry-v1/isosceles-request.json'


def payload() -> dict:
    return json.loads(_FIXTURE.read_text())


def ocr_payload() -> dict:
    data = payload()
    project_id = '11111111-1111-4111-8111-111111111111'
    material_id = '22222222-2222-4222-8222-222222222222'
    sources = [{
        'material_id': material_id, 'filename': 'problem.png', 'content_sha256': 'a' * 64,
        'page': 1, 'text': data['proposition'],
    }]
    bound = {'project_id': project_id, 'sources': sources}
    data.update({
        'source_kind': 'ocr', 'original_text': 'Prove exercise 2 in the attached figure.',
        'project_id': project_id,
        'material_context': {
            **bound, 'snapshot_sha256': hashlib.sha256(rfc8785.dumps(bound)).hexdigest(),
        },
        'material_citations': [{
            'material_id': material_id, 'page': 1, 'excerpt': data['proposition'],
        }],
    })
    return data


def confirm(data: dict) -> None:
    question = proposition_question(data['proposition'], 'en')
    data['context_turns'] = [{
        'question_id': hashlib.sha256(rfc8785.dumps(question)).hexdigest()[:24],
        'question': question['text'], 'answer': 'Yes',
    }]


def test_explicit_model_preserves_exact_input_and_returns_copies() -> None:
    data = payload()
    original = copy.deepcopy(data)
    problem = GeometryProblem.parse(data)
    assert problem.ready
    assert problem.role_ids == dict(A='a', B='b', C='c', M='m')
    assert problem.original_text == problem.statement == data['original_text']
    assert problem.to_data() == original
    data['objects'][0]['label'] = 'changed'
    returned = problem.to_data()
    returned['objects'][0]['label'] = 'also changed'
    roles = problem.role_ids
    roles['A'] = 'changed'
    assert problem.to_data() == original
    assert problem.role_ids['A'] == 'a'
    assert problem.sha256 == hashlib.sha256(rfc8785.dumps(original)).hexdigest()


def test_object_labels_do_not_change_role_identity() -> None:
    data = payload()
    data['objects'][0]['label'] = 'P'
    data['objects'][1]['label'] = 'Q'
    assert GeometryProblem.parse(data).role_ids == dict(A='a', B='b', C='c', M='m')


def test_misleading_drawing_never_changes_formal_hypotheses() -> None:
    data = payload()
    data['display_coordinates'] = {'a': [1, 0], 'b': [0, 0], 'c': [0, 0], 'm': [999, 999]}
    problem = GeometryProblem.parse(data)
    assert problem.ready
    assert problem.to_data()['hypotheses'] == payload()['hypotheses']
    del data['hypotheses'][0]
    with pytest.raises(GeometryInputError, match='three explicit hypotheses'):
        GeometryProblem.parse(data)


@pytest.mark.parametrize('change', [
    lambda d: d.update(extra='unreviewed'),
    lambda d: d.update(family='general_geometry'),
    lambda d: d['objects'][0].update(id='b'),
    lambda d: d['objects'][0].update(role='B'),
    lambda d: d['objects'][0].update(kind='vector'),
    lambda d: d['objects'][0].update(label='B'),
    lambda d: d['hypotheses'][0].update(predicate='equal_distance'),
    lambda d: d['hypotheses'][1].update(objects=['a', 'b', 'b', 'c']),
    lambda d: d['hypotheses'][2].update(objects=['b', 'm', 'c']),
    lambda d: d['conclusion'].update(objects=['a', 'b', 'm', 'c']),
    lambda d: d['conclusion'].update(id='h_midpoint'),
    lambda d: d['hypotheses'][0]['source_span'].update(excerpt='silently changed'),
    lambda d: d['hypotheses'][0]['source_span'].update(start=True),
    lambda d: d.update(proposition=d['proposition'] + ' changed'),
    lambda d: d.update(display_coordinates={'unknown': [0, 0]}),
    lambda d: d.update(display_coordinates={'a': [float('nan'), 0]}),
    lambda d: d.update(display_coordinates={'a': [float('inf'), 0]}),
    lambda d: d.update(display_coordinates={'a': [True, 0]}),
    lambda d: d.update(display_coordinates={'a': [10001, 0]}),
    lambda d: d.update(display_coordinates={'a': [10 ** 400, 0]}),
    lambda d: d.update(material_citations=''),
    lambda d: d.update(figures=[{'path': '/tmp/figure.png'}]),
])
def test_hard_negative_models_are_rejected(change) -> None:
    data = payload()
    change(data)
    with pytest.raises(GeometryInputError):
        GeometryProblem.parse(data)


def test_ambiguity_requires_clarification() -> None:
    data = payload()
    data['ambiguities'] = ['Does the equal-length mark mean AB = AC or AB = BC?']
    problem = GeometryProblem.parse(data)
    assert not problem.ready
    assert problem.clarification is not None
    assert data['ambiguities'][0] in problem.clarification['text']


def test_ocr_requires_exact_runtime_confirmation_and_preserves_sources() -> None:
    data = ocr_payload()
    unconfirmed = GeometryProblem.parse(data)
    assert not unconfirmed.ready
    assert unconfirmed.clarification == proposition_question(data['proposition'], 'en')
    confirm(data)
    confirmed = GeometryProblem.parse(data)
    assert confirmed.ready
    assert confirmed.to_data()['material_context'] == data['material_context']
    assert confirmed.original_text == data['original_text']
    assert confirmed.statement == data['proposition']


def test_forged_stale_or_corrected_ocr_confirmation_is_not_ready() -> None:
    data = ocr_payload()
    confirm(data)
    data['context_turns'][0]['question_id'] = 'forged'
    assert not GeometryProblem.parse(data).ready
    confirm(data)
    data['context_turns'].append({
        'question_id': 'correction', 'question': 'Which sides?', 'answer': 'AB = BC',
    })
    assert not GeometryProblem.parse(data).ready
    confirm(data)
    data['context_turns'][0]['question'] += ' '
    assert not GeometryProblem.parse(data).ready


def test_ocr_snapshot_and_excerpt_tampering_are_rejected() -> None:
    data = ocr_payload()
    data['material_context']['sources'][0]['text'] = 'changed'
    with pytest.raises(GeometryInputError, match='provenance'):
        GeometryProblem.parse(data)
    data = ocr_payload()
    data['material_citations'][0]['excerpt'] = 'not in the OCR page'
    with pytest.raises(GeometryInputError, match='provenance'):
        GeometryProblem.parse(data)


def test_existing_image_reference_is_retained_without_paths_or_binary() -> None:
    data = payload()
    image = {
        'id': '33333333-3333-4333-8333-333333333333', 'filename': 'triangle.png',
        'media_type': 'image/png', 'size_bytes': 350,
        'content_sha256': 'c' * 64, 'image_sha256': 'd' * 64,
    }
    data['figures'] = [image]
    problem = GeometryProblem.parse(data)
    assert problem.ready
    assert problem.to_data()['figures'] == [image]


def test_duplicate_figure_identity_is_rejected() -> None:
    data = payload()
    image = {
        'id': '33333333-3333-4333-8333-333333333333', 'filename': 'triangle.png',
        'media_type': 'image/png', 'size_bytes': 350,
        'content_sha256': 'c' * 64, 'image_sha256': 'd' * 64,
    }
    data['figures'] = [image, image]
    with pytest.raises(GeometryInputError, match='figure identities'):
        GeometryProblem.parse(data)


@pytest.mark.parametrize('location', ['figures', 'context_turns'])
@pytest.mark.parametrize('field', [
    'id', 'filename', 'media_type', 'size_bytes', 'content_sha256', 'image_sha256',
])
@pytest.mark.parametrize('malformed', [[], {}])
def test_malformed_nested_image_metadata_fails_closed(location, field, malformed) -> None:
    data = payload()
    image = {
        'id': '33333333-3333-4333-8333-333333333333', 'filename': 'triangle.png',
        'media_type': 'image/png', 'size_bytes': 350,
        'content_sha256': 'c' * 64, 'image_sha256': 'd' * 64,
    }
    image[field] = malformed
    if location == 'figures':
        data['figures'] = [image]
    else:
        data['context_turns'] = [{
            'question_id': 'question', 'question': 'Confirm?', 'answer': 'Yes',
            'attachments': [image],
        }]
    with pytest.raises(GeometryInputError):
        GeometryProblem.parse(data)


@pytest.mark.parametrize('location', ['role', 'label', 'id', 'source_kind', 'predicate'])
@pytest.mark.parametrize('malformed', [[], {}])
def test_unhashable_domain_fields_fail_closed(location, malformed) -> None:
    data = payload()
    if location == 'source_kind':
        data[location] = malformed
    elif location == 'predicate':
        data['hypotheses'][0][location] = malformed
    else:
        data['objects'][0][location] = malformed
    with pytest.raises(GeometryInputError):
        GeometryProblem.parse(data)


@pytest.mark.parametrize('depth', [2000, 20_000])
def test_deeply_nested_malformed_json_fails_closed(depth) -> None:
    data = payload()
    nested = []
    for _ in range(depth):
        nested = [nested]
    data['objects'][0]['label'] = nested
    with pytest.raises(GeometryInputError):
        GeometryProblem.parse(data)


def test_multibyte_proposition_uses_existing_confirmation_byte_bound() -> None:
    data = ocr_payload()
    data['proposition'] += 'あ' * 510
    assert len(data['proposition']) < 1600
    assert len(data['proposition'].encode('utf-8')) > 1600
    confirm(data)
    with pytest.raises(GeometryInputError, match='1600 UTF-8 bytes'):
        GeometryProblem.parse(data)


def test_long_original_ocr_input_is_retained_when_proposition_is_bounded() -> None:
    data = ocr_payload()
    data['original_text'] += 'あ' * 1000
    confirm(data)
    problem = GeometryProblem.parse(data)
    assert problem.ready
    assert problem.original_text == data['original_text']
