"""Static checks on the deployment files (Phase 6): ``render.yaml``, ``netlify.toml``, the hosted Dockerfile.

These catch the failures that would otherwise first appear during the Phase 7 deploy: a misspelled
environment variable, a secret committed to the Blueprint, or a service configuration that the app's own
startup guards would refuse.
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
import yaml

from app.core.config import Settings

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"

# Values a person enters in the Render dashboard for `sync: false` variables, shaped like the real thing.
PROMPTED_VALUES = {
    "CORS_ORIGINS": "https://codesage.netlify.app",
    "DATABASE_URL": "postgresql://u:p@ep-x-pooler.eu-central-1.aws.neon.tech/db?sslmode=require&channel_binding=require",
    "REDIS_HOST": "x.upstash.io", "REDIS_PORT": "6379", "REDIS_PASSWORD": "tok",
    "QDRANT_URL": "https://x.eu-central-1-0.aws.cloud.qdrant.io:6333", "QDRANT_API_KEY": "key",
    "CLOUDFLARE_ACCOUNT_ID": "acct", "CLOUDFLARE_API_TOKEN": "cf-tok", "GROQ_API_KEY": "gsk",
    "TURNSTILE_SECRET_KEY": "1x0000000000000000000000000000000AA",
    "GITHUB_CLIENT_ID": "id", "GITHUB_CLIENT_SECRET": "secret",
    "GITHUB_REDIRECT_URI": "https://codesage.netlify.app/auth/callback",
    "INDEXER_URL": "https://codesage-indexer.onrender.com", "INTERNAL_API_TOKEN": "i" * 32,
}
GENERATED_VALUE = "g" * 44  # what Render's generateValue produces: a base64 256-bit string
# Anything that is a credential must never be a literal in the (public) Blueprint.
SECRET_KEYS = {
    "DATABASE_URL", "REDIS_PASSWORD", "QDRANT_API_KEY", "CLOUDFLARE_API_TOKEN", "GROQ_API_KEY", "JWT_SECRET",
    "TURNSTILE_SECRET_KEY", "GITHUB_CLIENT_SECRET", "INTERNAL_API_TOKEN",
}


@pytest.fixture(scope="module")
def blueprint() -> dict:
    return yaml.safe_load((REPO / "render.yaml").read_text(encoding="utf-8"))


def services(blueprint) -> dict[str, dict]:
    return {s["name"]: s for s in blueprint["services"]}


def known_setting_names() -> set[str]:
    settings = Settings()
    names: set[str] = set()
    for group in vars(settings).values():
        fields = getattr(type(group), "model_fields", None)
        if fields:
            names.update(name.upper() for name in fields)
    return names


class TestRenderBlueprint:
    def test_there_are_exactly_two_free_docker_services_in_frankfurt(self, blueprint):
        found = services(blueprint)
        assert set(found) == {"codesage-api", "codesage-indexer"}
        for service in found.values():
            assert (service["type"], service["runtime"], service["plan"], service["region"]) == ("web", "docker", "free", "frankfurt")

    def test_both_build_the_hosted_image_from_the_backend_directory(self, blueprint):
        for service in services(blueprint).values():
            assert service["dockerfilePath"] == "./backend/Dockerfile.hosted" and service["dockerContext"] == "./backend"
            assert (REPO / service["dockerfilePath"]).is_file()

    def test_health_checks_use_the_cheap_liveness_route_not_the_deep_one(self, blueprint):
        for service in services(blueprint).values():
            assert service["healthCheckPath"] == "/health/live"  # /health would wake Neon and Qdrant every few seconds

    def test_deploys_are_started_by_ci_not_by_every_push(self, blueprint):
        for service in services(blueprint).values():
            assert service["autoDeployTrigger"] == "off"  # CI migrates first, then calls the deploy hook (Phase 8)

    def test_every_variable_is_a_real_setting(self, blueprint):
        known = known_setting_names()
        for name, service in services(blueprint).items():
            unknown = [e["key"] for e in service["envVars"] if e["key"].upper() not in known]
            assert not unknown, f"{name} sets variables the app does not read (typo?): {unknown}"

    def test_no_secret_is_written_into_the_file(self, blueprint):
        for name, service in services(blueprint).items():
            for entry in service["envVars"]:
                if entry["key"] in SECRET_KEYS:
                    assert "value" not in entry, f"{name}: {entry['key']} must be sync:false or generated, never a literal"
                    assert entry.get("sync") is False or entry.get("generateValue") is True

    def test_each_variable_has_exactly_one_source(self, blueprint):
        for service in services(blueprint).values():
            for entry in service["envVars"]:
                sources = [k for k in ("value", "sync", "generateValue") if k in entry]
                assert len(sources) == 1, f"{entry['key']} has sources {sources}"

    def test_no_duplicate_variables_within_a_service(self, blueprint):
        for service in services(blueprint).values():
            keys = [e["key"] for e in service["envVars"]]
            assert len(keys) == len(set(keys))

    def test_the_two_services_share_the_internal_token_and_the_data_layer_variables(self, blueprint):
        api, indexer = (services(blueprint)[n] for n in ("codesage-api", "codesage-indexer"))
        shared = {"INTERNAL_API_TOKEN", "DATABASE_URL", "REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD", "QDRANT_URL",
                  "QDRANT_API_KEY", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"}
        for service in (api, indexer):
            assert shared <= {e["key"] for e in service["envVars"]}

    def test_the_indexer_is_not_given_user_facing_secrets_it_does_not_need(self, blueprint):
        keys = {e["key"] for e in services(blueprint)["codesage-indexer"]["envVars"]}
        assert not keys & {"JWT_SECRET", "TURNSTILE_SECRET_KEY", "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "GROQ_API_KEY", "CORS_ORIGINS"}

    @pytest.mark.parametrize(("service_name", "role"), [("codesage-api", "api"), ("codesage-indexer", "indexer")])
    def test_each_services_environment_satisfies_the_apps_production_startup_guards(
        self, blueprint, monkeypatch, service_name, role
    ):
        """Build the environment Render would give the service, start the app's own settings on it, and ask the
        guards. If this passes, the service will not refuse to start on a configuration error."""
        for entry in services(blueprint)[service_name]["envVars"]:
            if "value" in entry:
                value = entry["value"]
            elif entry.get("generateValue"):
                value = GENERATED_VALUE
            else:
                value = PROMPTED_VALUES[entry["key"]]  # KeyError here = a new prompted variable this test must know about
            monkeypatch.setenv(entry["key"], str(value))

        settings = Settings()

        assert settings.app.role == role and settings.app.environment == "production"
        assert settings.production_problems() == [], settings.production_problems()
        # ...and the values take effect as intended:
        assert settings.indexing.indexing_backend == "postgres" and settings.llm.embedding_provider == "cloudflare"
        assert settings.database.prepared().pooled is True and settings.database.prepared().connect_args["ssl"] == "require"
        assert settings.redis.redis_ssl is True
        assert settings.app.allowed_hosts_list == ["*.onrender.com"]

    def test_the_api_is_told_where_the_indexer_is(self, blueprint):
        assert "INDEXER_URL" in {e["key"] for e in services(blueprint)["codesage-api"]["envVars"]}


class TestNetlifyConfig:
    @pytest.fixture(scope="class")
    def config(self) -> dict:
        return tomllib.loads((REPO / "netlify.toml").read_text(encoding="utf-8"))

    def test_it_points_at_the_frontend_directory_and_a_script_that_exists(self, config):
        build = config["build"]
        assert (REPO / build["base"] / "package.json").is_file()
        script = build["command"].removeprefix("npm run ").strip()
        scripts = json.loads((REPO / build["base"] / "package.json").read_text(encoding="utf-8"))["scripts"]
        assert script in scripts

    def test_the_build_is_skipped_for_commits_that_do_not_touch_the_frontend(self, config):
        ignore = config["build"]["ignore"]
        assert "git diff --quiet" in ignore and "$CACHED_COMMIT_REF" in ignore and "../netlify.toml" in ignore

    def test_the_node_version_is_one_next_14_supports(self, config):
        assert config["build"]["environment"]["NODE_VERSION"] in {"18", "20", "22"}

    def test_security_headers_do_not_include_a_csp_that_could_break_the_page(self, config):
        values = config["headers"][0]["values"]
        assert values["X-Content-Type-Options"] == "nosniff" and values["X-Frame-Options"] == "DENY"
        assert "Content-Security-Policy" not in values  # deliberately deferred: untested against Turnstile/Mermaid


class TestHostedImageFiles:
    def test_the_hosted_image_installs_only_pinned_runtime_dependencies(self):
        instructions = chr(10).join(
            line for line in (BACKEND / "Dockerfile.hosted").read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")  # comments explain *why* fastembed is absent, so they mention it
        )
        assert "requirements-base.txt" in instructions and "-c constraints-hosted.txt" in instructions
        assert "fastembed" not in instructions and "requirements.txt" not in instructions.replace("requirements-base.txt", "")

    def test_the_local_model_never_leaks_into_the_hosted_dependency_set(self):
        base = (BACKEND / "requirements-base.txt").read_text(encoding="utf-8").lower()
        pins = (BACKEND / "constraints-hosted.txt").read_text(encoding="utf-8").lower()
        assert "fastembed" not in base and "pytest" not in base
        assert "fastembed==" not in pins and "onnxruntime==" not in pins

    def test_local_requirements_still_include_everything_they_did_before(self):
        text = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
        assert "-r requirements-base.txt" in text and "fastembed" in text and "pytest" in text

    def test_every_runtime_dependency_is_pinned_for_the_hosted_build(self):
        names = {
            line.split("[")[0].split(">")[0].split("=")[0].strip().lower().replace("_", "-")
            for line in (BACKEND / "requirements-base.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        pinned = {
            line.split("==")[0].strip().lower().replace("_", "-")
            for line in (BACKEND / "constraints-hosted.txt").read_text(encoding="utf-8").splitlines()
            if "==" in line
        }
        assert names <= pinned, f"unpinned: {sorted(names - pinned)}"

    def test_neither_image_can_contain_local_data_or_secrets(self):
        ignore = (BACKEND / ".dockerignore").read_text(encoding="utf-8").splitlines()
        for pattern in (".env", "data/", "logs/"):
            assert pattern in ignore

    def test_the_hosted_image_listens_on_the_port_render_provides(self):
        dockerfile = (BACKEND / "Dockerfile.hosted").read_text(encoding="utf-8")
        assert "${PORT:-10000}" in dockerfile and "0.0.0.0" in dockerfile and "exec uvicorn" in dockerfile
