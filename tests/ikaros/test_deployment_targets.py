from pathlib import Path

from ikaros.dev.deployment_targets import DeploymentTargets


def test_deployment_targets_loads_external_config(tmp_path: Path):
    config_path = tmp_path / "deployment_targets.yaml"
    config_path.write_text(
        """targets:
  api:
    service: ikaros-api-blue
    image: ikaros-api-blue
""",
        encoding="utf-8",
    )

    targets = DeploymentTargets(config_path=str(config_path))
    ikaros = targets.get("ikaros")
    api = targets.get("api")

    assert ikaros == {
        "service": "ikaros",
        "image": "ikaros-core",
    }
    assert api == {
        "service": "ikaros-api-blue",
        "image": "ikaros-api-blue",
    }


def test_deployment_targets_defaults_to_runtime_config_path(
    tmp_path: Path, monkeypatch
):
    monkeypatch.delenv("X_DEPLOYMENT_TARGETS_FILE", raising=False)
    ikaros_home = tmp_path / ".ikaros"
    config_path = ikaros_home / "config" / "deployment_targets.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """targets:
  ikaros:
    service: ikaros-green
    image: ikaros-core-green
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("IKAROS_HOME", str(ikaros_home))

    targets = DeploymentTargets()

    assert targets.get("ikaros") == {
        "service": "ikaros-green",
        "image": "ikaros-core-green",
    }
