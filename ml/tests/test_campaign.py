"""Workflow gates around the extracted campaign; no actual training or inference."""

from types import SimpleNamespace

import pytest

from recognition import campaign, common


@pytest.fixture
def campaign_workspace(tmp_path, monkeypatch):
    from recognition import training, release

    monkeypatch.setattr(common, "ROOT", tmp_path)
    calls = []
    behavior = {"repeat_f1": 0.89, "missing_job": False}
    winner = {
        "experiment_id": "selected",
        "checkpoint_sha256": "checkpoint-test",
        "validation": {"macro_f1": 0.9},
    }
    args = SimpleNamespace(
        config=tmp_path / "baseline.json",
        campaign="test-campaign",
        version="new-candidate",
        formal=True,
    )
    bundle = tmp_path / "models/releases/new-candidate"
    metadata = {
        "experiment_id": "selected",
        "checkpoint_sha256": "checkpoint-test",
        "status": "frozen",
    }

    def sweep(config, name, stage, previous, execute):
        assert execute is True
        calls.append(("sweep", stage, previous))
        job = stage + "-winner"
        if not behavior["missing_job"]:
            common.write_json(
                tmp_path / "experiments/reports" / job / "result.json",
                {"status": "complete"},
            )
        plan = tmp_path / (stage + "-jobs.json")
        common.write_json(plan, {"jobs": [{"experiment_id": job}]})
        return plan

    def summarize(plan):
        path = plan.with_name(plan.stem + "-summary.json")
        common.write_json(path, {"winner": winner})
        return path

    def reproduce(path, seed):
        calls.append(("repeat", seed))
        return {
            "status": "complete",
            "experiment_id": "selected-repeat" + str(seed),
            "validation": {"macro_f1": behavior["repeat_f1"]},
        }

    def export(*arguments):
        calls.append(("export", arguments))
        common.write_json(bundle / "metadata.json", metadata)

    monkeypatch.setattr(training, "sweep", sweep)
    monkeypatch.setattr(training, "summarize", summarize)
    monkeypatch.setattr(training, "reproduce", reproduce)
    monkeypatch.setattr(release, "export", export)
    for name in ["verify", "evaluate", "benchmark"]:
        monkeypatch.setattr(
            release, name, lambda path, name=name: calls.append((name, path))
        )
    return args, bundle, metadata, calls, behavior


@pytest.mark.parametrize("repeat_f1,seeds", [(0.89, [43]), (0.78, [43, 44])])
def test_campaign_keeps_stage_order_and_repeats_large_gaps(
    campaign_workspace, repeat_f1, seeds
):
    args, bundle, metadata, calls, behavior = campaign_workspace
    behavior["repeat_f1"] = repeat_f1
    campaign.run(args)
    assert [item[1] for item in calls if item[0] == "sweep"] == [
        "learning_rate",
        "dropout",
        "fine_tune",
    ]
    assert [item[1] for item in calls if item[0] == "repeat"] == seeds
    assert [item[0] for item in calls][-3:] == ["verify", "evaluate", "benchmark"]
    exported = next(item[1] for item in calls if item[0] == "export")
    assert exported[2] is True
    assert (exported[4] is not None) == (44 in seeds)
    assert common.read_json(bundle / "metadata.json") == metadata


def test_incomplete_jobs_pause_before_any_release_operation(campaign_workspace):
    args, bundle, _, calls, behavior = campaign_workspace
    behavior["missing_job"] = True
    with pytest.raises(SystemExit, match="Paused with checkpoints"):
        campaign.run(args)
    assert not bundle.exists()
    assert all(item[0] == "sweep" for item in calls)


@pytest.mark.parametrize("status", ["verification_failed", "experimental"])
def test_formal_campaign_preserves_incompatible_existing_release(
    campaign_workspace, status
):
    args, bundle, metadata, calls, _ = campaign_workspace
    common.write_json(bundle / "metadata.json", dict(metadata, status=status))
    before = (bundle / "metadata.json").read_bytes()
    with pytest.raises(SystemExit, match="Existing release differs"):
        campaign.run(args)
    assert (bundle / "metadata.json").read_bytes() == before
    assert not any(
        item[0] in ["export", "verify", "evaluate", "benchmark"] for item in calls
    )
