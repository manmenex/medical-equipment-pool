"""PR24D Fix Round 1: static structural validation of
.github/workflows/cd-staging.yml -- proves the digest-pinned
artifact-identity contract and the image-scan blocking gate are wired
correctly, without needing to actually run the workflow.

Independent review (P1-A/P1-B) found that `migrate-and-verify` did not
depend on `image-scan` (so a CRITICAL Trivy failure could not actually
block migration/deploy) and that commit-SHA image tags -- mutable
registry pointers -- were being treated as immutable artifact identity.
These tests lock in the fix: every downstream job/step must consume the
digest-pinned `*_image_ref` outputs, `migrate-and-verify` must require
`image-scan`, and neither Trivy step may be soft-failed.

Pure YAML-structure assertions only -- no GitHub Actions runtime
required, consistent with PR24C/PR24D's "prove the tooling without
needing live infrastructure" precedent.
"""

from pathlib import Path

import pytest
import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "cd-staging.yml"


@pytest.fixture(scope="module")
def workflow():
    with WORKFLOW_PATH.open() as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def jobs(workflow):
    return workflow["jobs"]


def test_workflow_file_exists_and_parses():
    assert WORKFLOW_PATH.is_file()


def test_migrate_and_verify_depends_on_image_scan(jobs):
    needs = jobs["migrate-and-verify"]["needs"]
    assert "image-scan" in needs
    assert "build-push-images" in needs
    assert "resolve-ref" in needs


def test_image_scan_steps_have_no_soft_failure_escape_hatch(jobs):
    for step in jobs["image-scan"]["steps"]:
        assert "continue-on-error" not in step, f"image-scan step {step.get('name')!r} must not soft-fail"
        assert step.get("if") != "always()", f"image-scan step {step.get('name')!r} must not run unconditionally regardless of prior failure"


def test_build_push_images_steps_have_ids_for_digest_capture(jobs):
    steps = jobs["build-push-images"]["steps"]
    ids = {step.get("id") for step in steps if step.get("id")}
    assert "build_backend" in ids
    assert "build_frontend" in ids
    assert "validate_digests" in ids


def test_build_push_images_exports_digest_and_ref_outputs(jobs):
    outputs = jobs["build-push-images"]["outputs"]
    for key in (
        "backend_image_tag",
        "frontend_image_tag",
        "backend_image_digest",
        "frontend_image_digest",
        "backend_image_ref",
        "frontend_image_ref",
    ):
        assert key in outputs, f"build-push-images must export {key}"


def test_digest_validation_step_fails_closed_on_missing_or_malformed_digest(jobs):
    steps = jobs["build-push-images"]["steps"]
    validate_step = next(step for step in steps if step.get("id") == "validate_digests")
    run = validate_step["run"]
    assert "exit 1" in run
    assert "sha256:" in run


def test_trivy_scans_use_digest_pinned_refs_not_tags(jobs):
    trivy_steps = [step for step in jobs["image-scan"]["steps"] if "trivy" in step.get("uses", "").lower()]
    assert len(trivy_steps) == 2
    for step in trivy_steps:
        image_ref = step["with"]["image-ref"]
        assert "_image_ref" in image_ref, f"Trivy step {step.get('name')!r} must scan the digest-pinned *_image_ref, not a mutable tag: {image_ref!r}"
        assert "_image_tag" not in image_ref


def test_trivy_severity_policy_unchanged(jobs):
    trivy_steps = [step for step in jobs["image-scan"]["steps"] if "trivy" in step.get("uses", "").lower()]
    for step in trivy_steps:
        with_block = step["with"]
        assert with_block["severity"] == "CRITICAL"
        assert str(with_block["exit-code"]) == "1"
        assert with_block["ignore-unfixed"] is True


def test_migrate_and_verify_never_consumes_bare_image_tag_for_pull_or_run(jobs):
    for step in jobs["migrate-and-verify"]["steps"]:
        run = step.get("run", "")
        if "docker pull" in run or "docker run" in run:
            assert "_image_ref" in run, f"step {step.get('name')!r} must use the digest-pinned *_image_ref"
            assert "_image_tag" not in run, f"step {step.get('name')!r} must not consume the mutable *_image_tag for pull/run"


def test_migrate_and_verify_records_release_evidence_including_digests(jobs):
    steps = jobs["migrate-and-verify"]["steps"]
    evidence_step = next((step for step in steps if "evidence" in step.get("name", "").lower()), None)
    assert evidence_step is not None, "migrate-and-verify must record release evidence"
    run = evidence_step["run"]
    for key in ("source_sha", "backend_image_digest", "backend_image_ref", "frontend_image_digest", "frontend_image_ref"):
        assert key in run


def test_dependency_scan_remains_informational_and_unblocking(jobs):
    # Fix Round 1 deliberately does not change the dependency-scan
    # policy (task's own instruction: "do not re-litigate threshold
    # policy") -- this test guards against an accidental regression in
    # either direction.
    for step in jobs["dependency-scan"]["steps"]:
        if step.get("run") and ("pip-audit" in step["run"] or "npm audit" in step["run"]):
            assert step.get("continue-on-error") is True


def test_dependency_scan_not_in_migrate_and_verify_needs(jobs):
    # dependency-scan may remain parallel/informational -- it must not
    # be required to block migrate-and-verify (only image-scan blocks).
    assert "dependency-scan" not in jobs["migrate-and-verify"]["needs"]


def test_workflow_permissions_remain_least_privilege(jobs):
    assert jobs["build-push-images"]["permissions"]["packages"] == "write"
    assert jobs["image-scan"]["permissions"]["packages"] == "read"
    assert jobs["migrate-and-verify"]["permissions"]["packages"] == "read"


def test_workflow_still_manual_dispatch_only(workflow):
    # PyYAML (YAML 1.1) parses the unquoted `on:` key as the boolean
    # True, not the string "on" -- this repository's workflow file uses
    # the bare `on:` form (matching ci.yml's own convention), so the
    # parsed key really is `True` here, not a typo.
    triggers = workflow.get("on") or workflow.get(True)
    assert triggers is not None, "could not locate the workflow's trigger block"
    assert "workflow_dispatch" in triggers
    assert "push" not in triggers
    assert "pull_request" not in triggers
