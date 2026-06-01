"""Unit tests for scripts/keycloak_token.py — all HTTP is mocked."""
import sys
import os
import pytest
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.keycloak_token import fetch_token


def _mock_200(token: str = "fake.access.token"):
    return httpx.Response(200, json={"access_token": token, "token_type": "Bearer"})


def _mock_error(status: int = 401, text: str = "unauthorized"):
    return httpx.Response(status, text=text)


class TestFetchTokenClientCredentials:
    def test_returns_access_token(self, respx_mock):
        respx_mock.post(
            "http://kc.local/realms/gallery/protocol/openid-connect/token"
        ).mock(return_value=_mock_200("my.jwt.token"))

        token = fetch_token(
            keycloak_url="http://kc.local",
            realm="gallery",
            client_id="gallery-test-client",
            client_secret="secret",
            grant_type="client_credentials",
        )
        assert token == "my.jwt.token"

    def test_posts_correct_grant_type(self, respx_mock):
        route = respx_mock.post(
            "http://kc.local/realms/gallery/protocol/openid-connect/token"
        ).mock(return_value=_mock_200())

        fetch_token(
            keycloak_url="http://kc.local/",
            realm="gallery",
            client_id="my-client",
            client_secret="my-secret",
            grant_type="client_credentials",
        )

        request = route.calls.last.request
        body = dict(pair.split("=") for pair in request.content.decode().split("&"))
        assert body["grant_type"] == "client_credentials"
        assert body["client_id"] == "my-client"
        assert body["client_secret"] == "my-secret"

    def test_raises_on_error_status(self, respx_mock):
        respx_mock.post(
            "http://kc.local/realms/gallery/protocol/openid-connect/token"
        ).mock(return_value=_mock_error(401))

        with pytest.raises(RuntimeError, match="401"):
            fetch_token(
                keycloak_url="http://kc.local",
                realm="gallery",
                client_id="c",
                client_secret="s",
                grant_type="client_credentials",
            )


class TestFetchTokenPassword:
    def test_returns_access_token(self, respx_mock):
        respx_mock.post(
            "http://kc.local/realms/gallery/protocol/openid-connect/token"
        ).mock(return_value=_mock_200("user.jwt.token"))

        token = fetch_token(
            keycloak_url="http://kc.local",
            realm="gallery",
            client_id="gallery-app",
            client_secret="",
            grant_type="password",
            username="devuser",
            password="devpass",
        )
        assert token == "user.jwt.token"

    def test_posts_username_and_password(self, respx_mock):
        route = respx_mock.post(
            "http://kc.local/realms/gallery/protocol/openid-connect/token"
        ).mock(return_value=_mock_200())

        fetch_token(
            keycloak_url="http://kc.local",
            realm="gallery",
            client_id="gallery-app",
            client_secret="",
            grant_type="password",
            username="alice",
            password="secret123",
        )

        request = route.calls.last.request
        body = dict(pair.split("=") for pair in request.content.decode().split("&"))
        assert body["grant_type"] == "password"
        assert body["username"] == "alice"
        assert body["password"] == "secret123"

    def test_raises_without_credentials(self):
        with pytest.raises(ValueError, match="--username and --password"):
            fetch_token(
                keycloak_url="http://kc.local",
                realm="gallery",
                client_id="gallery-app",
                client_secret="",
                grant_type="password",
            )
