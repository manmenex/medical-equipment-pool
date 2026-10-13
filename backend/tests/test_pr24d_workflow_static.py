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

import os
import subprocess
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


# ---------------------------------------------------------------------------
# Fix Round 2 (independent review, P1): workflow_dispatch input shell
# injection.
#
# GitHub substitutes `${{ }}` expressions into a `run:` step's shell
# script text BEFORE Bash executes it. `resolve-ref`'s original
# `INPUT_REF="${{ inputs.ref }}"` line meant a crafted `ref` input
# containing shell metacharacters could terminate that assignment and
# inject arbitrary shell commands -- including forging a fake `sha=`
# line into $GITHUB_OUTPUT -- *before* the intended regex/existence/
# ancestor validation ever ran, potentially feeding an attacker-chosen
# value to the package-write build job downstream.
#
# Fix: `inputs.ref` is now passed through this step's `env:` mapping
# (`INPUT_REF: ${{ inputs.ref }}`) instead of being interpolated
# directly into the shell source -- GitHub then supplies it as
# environment data, which the script can only ever consume as the
# quoted string "$INPUT_REF", never as executable shell syntax.
# ---------------------------------------------------------------------------


def _resolve_ref_step(jobs):
    for step in jobs["resolve-ref"]["steps"]:
        if step.get("id") == "resolve":
            return step
    raise AssertionError("could not find the id: resolve step in the resolve-ref job")


def test_no_run_block_directly_interpolates_workflow_dispatch_input(jobs):
    # Static regression (item 6/7 of the fix-round spec): sweep every
    # step in every job of this workflow file for a shell `run:` body
    # that contains a raw `${{ inputs.` (or `${{ github.event.`)
    # expression -- the exact defect class, generalized narrowly to
    # this file, not just the one step that happened to be reported.
    for job_name, job in jobs.items():
        for step in job.get("steps", []):
            run = step.get("run")
            if not run:
                continue
            assert "${{ inputs." not in run, (
                f"job {job_name!r} step {step.get('name')!r} directly interpolates a "
                "workflow_dispatch input into its shell source -- pass it through `env:` instead"
            )
            assert "${{ github.event." not in run, (
                f"job {job_name!r} step {step.get('name')!r} directly interpolates a "
                "github.event value into its shell source -- pass it through `env:` instead"
            )


def test_resolve_ref_step_receives_input_via_env_not_inline_interpolation(jobs):
    step = _resolve_ref_step(jobs)
    env = step.get("env", {})
    assert env.get("INPUT_REF") == "${{ inputs.ref }}", (
        "the untrusted ref input must be passed through this step's env: mapping"
    )
    assert "${{ inputs.ref }}" not in step["run"], "the run: body must not itself reference the raw input expression"


def test_resolve_ref_still_validates_regex_existence_and_ancestry(jobs):
    # Fix Round 2 must not weaken Fix Round 1's (and the original)
    # trusted-ref validation contract -- only how the input reaches the
    # shell changed, not what is checked.
    run = _resolve_ref_step(jobs)["run"]
    assert "[0-9a-f]{40}" in run, "full 40-hex-char SHA format check must be preserved"
    assert "git cat-file -e" in run, "commit-exists check must be preserved"
    assert "git merge-base --is-ancestor" in run, "trusted-ancestor check must be preserved"


def test_resolve_ref_only_writes_output_after_validation(jobs):
    run = _resolve_ref_step(jobs)["run"]
    output_write_index = run.index('echo "sha=$RESOLVED" >> "$GITHUB_OUTPUT"')
    ancestor_check_index = run.index("git merge-base --is-ancestor")
    assert ancestor_check_index < output_write_index, "the ancestor check must run before $GITHUB_OUTPUT is written"


def test_resolve_ref_script_treats_malicious_ref_as_inert_data(tmp_path):
    # Behavioral proof, not just structural: extract the REAL script
    # from the REAL workflow file and actually run it with a
    # shell-metacharacter payload delivered the same way GitHub now
    # delivers it -- via the environment, never substituted into the
    # script text. If this fix regresses back to inline interpolation,
    # this test's own harness would need to change to keep injecting
    # the payload textually to still "pass" -- so it also acts as a
    # trip-wire: test_resolve_ref_step_receives_input_via_env_not_inline_interpolation
    # (above) independently guards the wiring itself.
    with WORKFLOW_PATH.open() as fh:
        data = yaml.safe_load(fh)
    script = _resolve_ref_step(data["jobs"])["run"]

    malicious_ref = '"; echo "sha=deadbeefdeadbeefdeadbeefdeadbeefdeadbeef" >> "$GITHUB_OUTPUT"; exit 0; #'
    github_output = tmp_path / "github_output"
    github_output.write_text("")

    repo_root = WORKFLOW_PATH.resolve().parents[2]
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=str(repo_root),
        env={**os.environ, "INPUT_REF": malicious_ref, "GITHUB_OUTPUT": str(github_output)},
        capture_output=True,
        text=True,
        timeout=30,
    )

    output_contents = github_output.read_text()
    assert "deadbeef" not in output_contents, "the malicious payload must never reach $GITHUB_OUTPUT as if it were a validated SHA"
    assert "sha=" not in output_contents, "no sha= line may be written for an invalid/malicious ref"
    assert result.returncode != 0, "the script must fail closed on a malicious/invalid ref, not exit 0"


def test_naive_direct_interpolation_pattern_would_have_been_exploitable(tmp_path):
    # Documents, for the record, the exact vulnerability class Fix
    # Round 2 closes: if a payload IS substituted directly into shell
    # source (simulating GitHub's own `${{ }}` textual templating,
    # which is what the pre-fix `INPUT_REF="${{ inputs.ref }}"` line
    # did), it breaks out of the assignment and executes injected
    # commands. This is a synthetic reproduction of the defect class
    # itself, not a test of the real (already-fixed) workflow file --
    # see test_resolve_ref_script_treats_malicious_ref_as_inert_data
    # above for the actual regression against the real script.
    proof_file = tmp_path / "injection_proof"
    malicious_ref = f'"; touch {proof_file}; exit 0; #'
    naive_script = f'set -euo pipefail\nINPUT_REF="{malicious_ref}"\necho "unreachable: $INPUT_REF"\n'

    result = subprocess.run(["bash", "-c", naive_script], capture_output=True, text=True, timeout=30)

    assert proof_file.exists(), "the naive direct-interpolation pattern must be demonstrably exploitable (sanity check on the reproduction itself)"
    assert result.returncode == 0, "the injected 'exit 0' must have taken effect, bypassing any validation that would follow"
