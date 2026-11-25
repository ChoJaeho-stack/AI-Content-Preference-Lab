"""Start the real FastAPI app with test catalog data and a deterministic Gemini fixture."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
CATALOG = [
    {"id": 1, "type": "movie", "title": "Comedy favorite", "genre_ids": [12, 14, 16, 18, 28, 35], "rating": 8},
    {"id": 2, "type": "movie", "title": "Horror favorite", "genre_ids": [27], "rating": 8},
    {"id": 3, "type": "movie", "title": "Second comedy favorite", "genre_ids": [35], "rating": 8},
    {"id": 11, "type": "movie", "title": "Comedy candidate", "genre_ids": [35], "rating": 8},
    {"id": 12, "type": "movie", "title": "Horror candidate", "genre_ids": [27], "rating": 8},
]


def fixture_response(prompt):
    profile_line = prompt.split("\n찜 기반 개인화 참고 정보:\n", 1)[1].splitlines()[0]
    profile = json.loads(profile_line)
    if "Comedy favorite" in profile["favorite_titles"]:
        assert set(profile["favorite_titles"]) == {"Comedy favorite", "Second comedy favorite"}
        assert profile["preferred_genres"] == ["코미디", "모험", "판타지", "애니메이션", "드라마"]
    else:
        assert profile["favorite_titles"] == ["Horror favorite"]
        assert profile["preferred_genres"] == ["공포"]
    # Exercise the real candidate scoring by selecting the first non-favorite candidate.
    candidate_line = prompt.split("\n콘텐츠 데이터:\n", 1)[1].splitlines()[0]
    candidates = json.loads(candidate_line)
    best = next(item for item in candidates if item["id"] in (11, 12))
    recent = [item["id"] for item in candidates if item["recently_recommended"]]
    return SimpleNamespace(text=json.dumps({
        "taste_analysis": "recent:" + ",".join(map(str, recent)),
        "recommendations": [{
            "id": best["id"], "type": best["type"], "match_score": 85,
            "reason": "Deterministic recommendation test fixture",
        }],
    }))


def serve(port_file, live_gemini=False):
    if live_gemini:
        from threading import Lock
        import ai_server

        one_call = Lock()

        def generate_once(prompt):
            profile = json.loads(prompt.split("\n찜 기반 개인화 참고 정보:\n", 1)[1].splitlines()[0])
            candidates = json.loads(prompt.split("\n콘텐츠 데이터:\n", 1)[1].splitlines()[0])
            if (profile["favorite_titles"] != ["Second comedy favorite"]
                    or profile["preferred_genres"] != ["코미디"]
                    or not any(item["id"] == 1 and item["recently_recommended"] for item in candidates)):
                raise RuntimeError("Live Gemini test requires the isolated preference fixture")
            if not one_call.acquire(blocking=False):
                raise RuntimeError("Live Gemini test permits only one generation attempt")
            return ai_server.client.models.generate_content(
                model=ai_server.MODEL,
                contents=prompt,
                config=ai_server.types.GenerateContentConfig(response_mime_type="application/json"),
            )

        ai_server.generate_with_retry = generate_once
    else:
        with patch("google.genai.Client"):
            import ai_server
        ai_server.generate_with_retry = fixture_response
    import uvicorn

    ai_server.get_contents = lambda: CATALOG
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        Path(port_file).write_text(str(listener.getsockname()[1]), encoding="ascii")
        uvicorn.Server(uvicorn.Config(ai_server.app, log_level="warning")).run(sockets=[listener])


def run_tests(live_gemini=False):
    from dotenv import dotenv_values

    config = dotenv_values(ROOT / ".env")
    environment = os.environ.copy()
    if not environment.get("DB_PASSWORD") and config.get("DB_PASSWORD"):
        environment["DB_PASSWORD"] = config["DB_PASSWORD"]
    if not environment.get("DB_PASSWORD"):
        raise SystemExit("Set DB_PASSWORD for the MySQL fixture session")
    server_environment = os.environ.copy()
    if live_gemini:
        key = environment.get("GEMINI_API_KEY") or config.get("GEMINI_API_KEY")
        if not key:
            raise SystemExit("Set GEMINI_API_KEY for the explicitly approved live test")
        server_environment["GEMINI_API_KEY"] = key
        environment["CONTENTLAB_RECOMMEND_LIVE_GEMINI"] = "true"
    environment.pop("GEMINI_API_KEY", None)
    test_name = ("RecommendationEndToEndTests#liveGeminiRecommendationIsSaved"
                 if live_gemini else "RecommendationEndToEndTests")
    maven_repository = Path(environment.get("MAVEN_REPO_LOCAL", ROOT / ".maven-cache")).resolve()

    with tempfile.TemporaryDirectory(prefix="contentlab-recommendation-e2e-") as directory:
        port_file = Path(directory) / "port"
        (Path(directory) / ".env").touch()
        # Keep builds away from the running application's DevTools classpath.
        source = ROOT / "contentlab"
        fixture_project = Path(directory) / "contentlab"
        fixture_project.mkdir()
        for name in ("pom.xml", "mvnw.cmd"):
            shutil.copy2(source / name, fixture_project / name)
        for name in (".mvn", "src"):
            shutil.copytree(source / name, fixture_project / name)
        process = subprocess.Popen(
            [sys.executable, __file__, "--serve-live" if live_gemini else "--serve", str(port_file)],
            cwd=ROOT, env=server_environment, stdout=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 20
            while not port_file.exists() or not port_file.stat().st_size:
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("FastAPI test server failed to start")
                time.sleep(0.05)
            port = int(port_file.read_text(encoding="ascii"))
            environment["CONTENTLAB_RECOMMEND_E2E"] = "true"
            environment["CONTENTLAB_AI_RECOMMEND_URL"] = f"http://127.0.0.1:{port}/recommend"
            return subprocess.run(
                ["cmd.exe", "/d", "/c", "mvnw.cmd", "-B",
                 f"-Dmaven.repo.local={maven_repository}",
                 f"-Dtest={test_name}", "test"],
                cwd=fixture_project, env=environment,
            ).returncode
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in {"--serve", "--serve-live"}:
        serve(sys.argv[2], live_gemini=sys.argv[1] == "--serve-live")
    elif sys.argv[1:] in ([], ["--live-gemini"]):
        raise SystemExit(run_tests(live_gemini=sys.argv[1:] == ["--live-gemini"]))
    else:
        raise SystemExit("Usage: py recommendation_e2e.py [--live-gemini]")
