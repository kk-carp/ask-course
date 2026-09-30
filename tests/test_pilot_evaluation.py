from scripts.evaluate_pilot import check_result


def test_wrong_course_evidence_is_a_serious_failure():
    result = {"hit": True, "fact_sources": [{"source": "/detail/43", "status": "official"}]}
    errors = check_result(result, {"expected_hit": True, "expected_source": "/detail/99", "require_sources": True})
    assert any(x.startswith("严重") for x in errors)


def test_conflicting_material_can_have_sources_without_a_verified_hit():
    result = {"hit": False, "fact_sources": [{"source": "test.md", "status": "conflict"}]}
    assert not check_result(result, {"expected_hit": False, "require_sources": True, "expected_fact_status": "conflict"})


def test_wrong_adviser_and_unknown_purchase_are_serious_failures():
    result = {"owner": {"configured": True, "topic_key": "43"},
              "related_courses": [{"id": "999999", "purchase_url": "https://invalid.test"}]}
    errors = check_result(result, {"expected_owner_topic_key": "99", "no_purchase": True})
    assert sum(x.startswith("严重") for x in errors) == 2
