"""
Unit tests for the HttpClient class and the create_http_client factory.
"""

from unittest.mock import MagicMock

import pytest
import requests
from authlib.integrations.base_client import OAuthError
from pytest_mock import MockerFixture

from cli.http_client import (
    AuthenticationError,
    HttpClient,
    create_http_client,
)


@pytest.fixture(name="mock_on_auth_failure")
def _mock_on_auth_failure() -> MagicMock:
    """
    A mock on_auth_failure callback.
    """
    return MagicMock()


@pytest.fixture(name="mock_session")
def _mock_session() -> MagicMock:
    """
    A mock HTTP session.
    """
    return MagicMock(spec=requests.Session)


@pytest.fixture(name="http_client")
def _http_client(mock_on_auth_failure: MagicMock, mock_session: MagicMock) -> HttpClient:
    """
    An HttpClient configured with a mock session and mock auth callback.
    """
    return HttpClient(
        base_url="https://example.com/api/v1",
        on_auth_failure=mock_on_auth_failure,
        session=mock_session,
    )


class TestHttpClientInit:
    """
    Tests for the `HttpClient` initialization.
    """

    def test_init_with_custom_base_url(
        self,
        mock_on_auth_failure: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """
        Test initialization with a custom base URL.
        """
        # when
        client = HttpClient(
            base_url="https://custom-server.com/api",
            on_auth_failure=mock_on_auth_failure,
            session=mock_session,
        )

        # then
        assert client.base_url == "https://custom-server.com/api"

    def test_init_strips_trailing_slash(
        self,
        mock_on_auth_failure: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """
        Test that a trailing slash is removed from the base URL.
        """
        # when
        client = HttpClient(
            base_url="https://server.com/api/",
            on_auth_failure=mock_on_auth_failure,
            session=mock_session,
        )

        # then
        assert client.base_url == "https://server.com/api"

    def test_insecure_passes_verify_false_in_requests(self) -> None:
        """
        Test that insecure=True causes verify=False to be passed in HTTP requests.
        """
        # given
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"experiments": []}
        mock_session.request.return_value = mock_response

        client = HttpClient(
            base_url="https://example.com",
            on_auth_failure=MagicMock(),
            session=mock_session,
            insecure=True,
        )

        # when
        client.list_experiments()

        # then
        mock_session.request.assert_called_once_with(
            method="get",
            url="https://example.com/experiments",
            headers={"Content-Type": "application/json"},
            json=None,
            timeout=30,
            verify=False,
        )

    def test_secure_by_default_passes_verify_true(self) -> None:
        """
        Test that insecure defaults to False and verify=True is passed in requests.
        """
        # given
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"experiments": []}
        mock_session.request.return_value = mock_response

        client = HttpClient(
            base_url="https://example.com",
            on_auth_failure=MagicMock(),
            session=mock_session,
        )

        # when
        client.list_experiments()

        # then
        mock_session.request.assert_called_once_with(
            method="get",
            url="https://example.com/experiments",
            headers={"Content-Type": "application/json"},
            json=None,
            timeout=30,
            verify=True,
        )


class TestHttpClientCreateExperiment:
    """
    Tests for the `create_experiment` method.
    """

    def test_create_experiment_success(
        self, http_client: HttpClient, mock_session: MagicMock
    ) -> None:
        """
        Test successful experiment creation.
        """
        # given
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"metadata": {"name": "test-exp"}}
        mock_session.request.return_value = mock_response

        # when
        result = http_client.create_experiment({"metadata": {"name": "test-exp"}})

        # then
        assert result == {"metadata": {"name": "test-exp"}}
        mock_session.request.assert_called_once_with(
            method="post",
            url="https://example.com/api/v1/experiments",
            headers={"Content-Type": "application/json"},
            json={"metadata": {"name": "test-exp"}},
            timeout=30,
            verify=True,
        )

    def test_create_experiment_http_error_with_json(
        self, http_client: HttpClient, mock_session: MagicMock
    ) -> None:
        """
        Test that create_experiment handles an HTTP error with a JSON response.
        """
        # given
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": "Bad request"}
        http_error = requests.exceptions.HTTPError()
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error
        mock_session.request.return_value = mock_response

        # when / then
        with pytest.raises(Exception, match="Failed to create experiment: Bad request"):
            http_client.create_experiment({"metadata": {"name": "test"}})

    def test_create_experiment_http_error_with_text(
        self, http_client: HttpClient, mock_session: MagicMock
    ) -> None:
        """
        Test that create_experiment handles an HTTP error with a text (non-JSON) response.
        """
        # given
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.side_effect = ValueError("Not JSON")
        mock_response.text = "Server error"
        http_error = requests.exceptions.HTTPError()
        http_error.response = mock_response
        mock_response.raise_for_status.side_effect = http_error
        mock_session.request.return_value = mock_response

        # when / then
        with pytest.raises(Exception, match="Failed to create experiment: Server error"):
            http_client.create_experiment({"metadata": {"name": "test"}})

    def test_create_experiment_connection_error(
        self, http_client: HttpClient, mock_session: MagicMock
    ) -> None:
        """
        Test that create_experiment handles connection errors.
        """
        # given
        mock_session.request.side_effect = requests.exceptions.ConnectionError("Connection failed")

        # when / then
        with pytest.raises(Exception, match="Failed to connect to backend server"):
            http_client.create_experiment({"metadata": {"name": "test"}})


class TestHttpClientGetExperiment:
    """
    Tests for the `get_experiment` method.
    """

    def test_get_experiment_success(self, http_client: HttpClient, mock_session: MagicMock) -> None:
        """
        Test successful get experiment.
        """
        # given
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"metadata": {"name": "test-exp"}}
        mock_session.request.return_value = mock_response

        # when
        result = http_client.get_experiment("test-exp")

        # then
        assert result == {"metadata": {"name": "test-exp"}}
        mock_session.request.assert_called_once_with(
            method="get",
            url="https://example.com/api/v1/experiments/test-exp",
            headers={"Content-Type": "application/json"},
            json=None,
            timeout=30,
            verify=True,
        )

    def test_get_experiment_error(self, http_client: HttpClient, mock_session: MagicMock) -> None:
        """
        Test that get_experiment handles errors.
        """
        # given
        mock_session.request.side_effect = requests.exceptions.RequestException("Error")

        # when / then
        with pytest.raises(Exception, match="Failed to get experiment"):
            http_client.get_experiment("test-exp")


class TestHttpClientListExperiments:
    """
    Tests for the `list_experiments` method.
    """

    def test_list_experiments_success(
        self, http_client: HttpClient, mock_session: MagicMock
    ) -> None:
        """
        Test successful list experiments.
        """
        # given
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "experiments": [{"metadata": {"name": "exp1"}}, {"metadata": {"name": "exp2"}}]
        }
        mock_session.request.return_value = mock_response

        # when
        result = http_client.list_experiments()

        # then
        assert result == {
            "experiments": [{"metadata": {"name": "exp1"}}, {"metadata": {"name": "exp2"}}]
        }
        mock_session.request.assert_called_once_with(
            method="get",
            url="https://example.com/api/v1/experiments",
            headers={"Content-Type": "application/json"},
            json=None,
            timeout=30,
            verify=True,
        )

    def test_list_experiments_error(self, http_client: HttpClient, mock_session: MagicMock) -> None:
        """
        Test that list_experiments handles errors.
        """
        # given
        mock_session.request.side_effect = requests.exceptions.RequestException("Error")

        # when / then
        with pytest.raises(Exception, match="Failed to list experiments"):
            http_client.list_experiments()


class TestHttpClientDeleteExperiment:
    """
    Tests for the `delete_experiment` method.
    """

    def test_delete_experiment_success(
        self, http_client: HttpClient, mock_session: MagicMock
    ) -> None:
        """
        Test successful delete experiment.
        """
        # given
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": "Deleted"}
        mock_session.request.return_value = mock_response

        # when
        result = http_client.delete_experiment("test-exp")

        # then
        assert result == {"message": "Deleted"}
        mock_session.request.assert_called_once_with(
            method="delete",
            url="https://example.com/api/v1/experiments/test-exp",
            headers={"Content-Type": "application/json"},
            json=None,
            timeout=30,
            verify=True,
        )

    def test_delete_experiment_error(
        self, http_client: HttpClient, mock_session: MagicMock
    ) -> None:
        """
        Test that delete_experiment handles errors.
        """
        # given
        mock_session.request.side_effect = requests.exceptions.RequestException("Error")

        # when / then
        with pytest.raises(Exception, match="Failed to delete experiment"):
            http_client.delete_experiment("test-exp")


class TestHttpClientDeleteExperimentsBatch:
    """
    Tests for the `delete_experiments_batch` method.
    """

    def test_delete_experiments_batch_all_success(
        self, http_client: HttpClient, mock_session: MagicMock
    ) -> None:
        """
        Test successful batch deletion of multiple experiments.
        """
        # given
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": "Deleted"}
        mock_session.request.return_value = mock_response

        # when
        results = http_client.delete_experiments_batch(["exp1", "exp2", "exp3"])

        # then
        assert len(results) == 3
        assert results["exp1"]["success"] is True
        assert results["exp2"]["success"] is True
        assert results["exp3"]["success"] is True
        assert mock_session.request.call_count == 3

    def test_delete_experiments_batch_partial_failure(
        self, http_client: HttpClient, mock_session: MagicMock
    ) -> None:
        """
        Test batch deletion with some failures.
        """
        # given
        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.json.return_value = {"message": "Deleted"}

        # First experiment succeeds, second fails, third succeeds
        mock_session.request.side_effect = [
            mock_success,
            requests.exceptions.RequestException("Not found"),
            mock_success,
        ]

        # when
        results = http_client.delete_experiments_batch(["exp1", "exp2", "exp3"])

        # then
        assert len(results) == 3
        assert results["exp1"]["success"] is True
        assert results["exp2"]["success"] is False
        assert "Not found" in results["exp2"]["error"]
        assert results["exp3"]["success"] is True
        assert mock_session.request.call_count == 3

    def test_delete_experiments_batch_empty_list(
        self, http_client: HttpClient, mock_session: MagicMock
    ) -> None:
        """
        Test batch deletion with empty list.
        """
        # when
        results = http_client.delete_experiments_batch([])

        # then
        assert len(results) == 0
        mock_session.request.assert_not_called()


class TestAuthenticationHandling:
    """
    Tests for 401 authentication error handling in the `HttpClient`.
    """

    def test_401_with_reauth_raising_error(self) -> None:
        """
        Test that a 401 response triggers the on_auth_failure callback, and when
        it raises, an AuthenticationError is propagated.
        """
        # given
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_session.request.return_value = mock_response
        mock_reauth = MagicMock(side_effect=Exception("Reauth failed"))

        client = HttpClient(
            base_url="https://example.com/api/v1",
            on_auth_failure=mock_reauth,
            session=mock_session,
        )

        # when / then
        with pytest.raises(AuthenticationError, match="credentials have expired"):
            client.list_experiments()
        mock_reauth.assert_called_once()

    def test_401_with_successful_reauth(self) -> None:
        """
        Test that a 401 response triggers re-authentication and retries the request
        successfully.
        """
        # given
        mock_session = MagicMock()
        mock_401 = MagicMock()
        mock_401.status_code = 401
        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {"experiments": []}
        mock_session.request.return_value = mock_401

        new_session = MagicMock()
        new_session.request.return_value = mock_200
        mock_reauth = MagicMock(return_value=new_session)

        client = HttpClient(
            base_url="https://example.com/api/v1",
            on_auth_failure=mock_reauth,
            session=mock_session,
        )

        # when
        result = client.list_experiments()

        # then
        assert result == {"experiments": []}
        mock_reauth.assert_called_once()
        new_session.request.assert_called_once()

    def test_401_after_reauth_retry_raises_authentication_error(self) -> None:
        """
        Test that a 401 on the retry attempt (after successful re-auth) raises
        AuthenticationError.
        """
        # given
        mock_session = MagicMock()
        mock_401 = MagicMock()
        mock_401.status_code = 401
        mock_session.request.return_value = mock_401

        new_session = MagicMock()
        new_session.request.return_value = mock_401
        mock_reauth = MagicMock(return_value=new_session)

        client = HttpClient(
            base_url="https://example.com/api/v1",
            on_auth_failure=mock_reauth,
            session=mock_session,
        )

        # when / then
        with pytest.raises(AuthenticationError, match="credentials have expired"):
            client.list_experiments()

    def test_insecure_passes_verify_false_after_reauth(self) -> None:
        """
        Test that insecure=True passes verify=False to the new session's
        requests after re-authentication.
        """
        # given
        mock_session = MagicMock()
        mock_401 = MagicMock()
        mock_401.status_code = 401
        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {"experiments": []}
        mock_session.request.return_value = mock_401

        new_session = MagicMock()
        new_session.request.return_value = mock_200
        mock_reauth = MagicMock(return_value=new_session)

        client = HttpClient(
            base_url="https://example.com/api/v1",
            on_auth_failure=mock_reauth,
            session=mock_session,
            insecure=True,
        )

        # when
        client.list_experiments()

        # then
        mock_session.request.assert_called_once_with(
            method="get",
            url="https://example.com/api/v1/experiments",
            headers={"Content-Type": "application/json"},
            json=None,
            timeout=30,
            verify=False,
        )
        new_session.request.assert_called_once_with(
            method="get",
            url="https://example.com/api/v1/experiments",
            headers={"Content-Type": "application/json"},
            json=None,
            timeout=30,
            verify=False,
        )

    def test_oauth_error_triggers_reauth_and_retry(self) -> None:
        """
        Test that an OAuthError during token refresh triggers re-authentication
        and retries the request.
        """
        # given
        mock_session = MagicMock()
        oauth_error = OAuthError(error="invalid_grant", description="Token is not active")
        mock_session.request.side_effect = oauth_error

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {"experiments": []}
        new_session = MagicMock()
        new_session.request.return_value = mock_200
        mock_reauth = MagicMock(return_value=new_session)

        client = HttpClient(
            base_url="https://example.com/api/v1",
            on_auth_failure=mock_reauth,
            session=mock_session,
        )

        # when
        result = client.list_experiments()

        # then
        assert result == {"experiments": []}
        mock_reauth.assert_called_once()
        new_session.request.assert_called_once()

    def test_oauth_error_with_reauth_failure_raises_authentication_error(self) -> None:
        """
        Test that an OAuthError during token refresh followed by a failed
        re-authentication raises AuthenticationError.
        """
        # given
        mock_session = MagicMock()
        oauth_error = OAuthError(error="invalid_grant", description="Token is not active")
        mock_session.request.side_effect = oauth_error
        mock_reauth = MagicMock(side_effect=Exception("Reauth failed"))

        client = HttpClient(
            base_url="https://example.com/api/v1",
            on_auth_failure=mock_reauth,
            session=mock_session,
        )

        # when / then
        with pytest.raises(AuthenticationError, match="credentials have expired"):
            client.list_experiments()
        mock_reauth.assert_called_once()


class TestCreateHttpClient:
    """
    Tests for the `create_http_client` factory function.
    """

    def test_no_auth_returns_unauthenticated_client(self, mocker: MockerFixture) -> None:
        """
        Test that create_http_client with no_auth=True returns an unauthenticated client.
        """
        # given
        mock_get_endpoint = mocker.patch(
            "cli.http_client.get_api_endpoint", return_value="https://platform.hiverge.ai/api/v1"
        )

        # when
        client = create_http_client(no_auth=True)

        # then
        assert client.base_url == "https://platform.hiverge.ai/api/v1"
        mock_get_endpoint.assert_called_once()
        with pytest.raises(AuthenticationError, match="Authentication is not configured"):
            client._on_auth_failure()

    def test_no_organization_id_raises_authentication_error(self, mocker: MockerFixture) -> None:
        """
        Test that create_http_client raises AuthenticationError when no
        organization_id is provided.
        """
        # given
        mocker.patch(
            "cli.http_client.get_api_endpoint", return_value="https://platform.hiverge.ai/api/v1"
        )

        # when / then
        with pytest.raises(AuthenticationError, match="No organization ID configured"):
            create_http_client()

    def test_with_organization_id_creates_authenticated_client(
        self,
        mocker: MockerFixture,
    ) -> None:
        """
        Test that create_http_client with an explicit organization_id creates
        an authenticated client using the session manager.
        """
        # given
        mocker.patch(
            "cli.http_client.get_api_endpoint", return_value="https://platform.hiverge.ai/api/v1"
        )
        mock_create_sm = mocker.patch("cli.http_client.create_session_manager")
        mock_sm = MagicMock()
        mock_session = MagicMock()
        mock_sm.create_session.return_value = mock_session
        mock_create_sm.return_value = mock_sm

        # when
        client = create_http_client(organization_id="my-org")

        # then
        assert client.base_url == "https://platform.hiverge.ai/api/v1"
        mock_create_sm.assert_called_once_with(
            organization_id="my-org",
            base_url="https://platform.hiverge.ai/api/v1",
            insecure=False,
        )
        mock_sm.create_session.assert_called_once()

    def test_insecure_flag_is_passed_through(self, mocker: MockerFixture) -> None:
        """
        Test that the insecure flag is passed through to the unauthenticated client.
        """
        # given
        mocker.patch(
            "cli.http_client.get_api_endpoint", return_value="https://platform.hiverge.ai/api/v1"
        )

        # when
        client = create_http_client(no_auth=True, insecure=True)

        # then
        assert client._insecure is True
