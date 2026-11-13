import httpx

from evals import run_flow


def test_existing_private_session_is_reused_without_republishing_bootstrap_credentials():
    cookie = "KPLASMA_LOCAL_SESSION=" + "A" * 43
    with httpx.Client(base_url="http://127.0.0.1:8080", trust_env=False) as client:
        run_flow.bootstrap_local_session(client, "http://127.0.0.1:5198", None, session_cookie=cookie)
        assert client.cookies.get("KPLASMA_LOCAL_SESSION") == "A" * 43
        assert client.headers["Origin"] == "http://127.0.0.1:5198"
        assert client.headers["Sec-Fetch-Site"] == "same-site"
