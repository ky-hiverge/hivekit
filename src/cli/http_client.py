"""
HTTP client for communicating with the Hive backend server.
"""

import logging
from http import HTTPStatus
from typing import Any, Callable, Dict, Optional

import requests
from authlib.integrations.base_client import OAuthError
from rich.console import Console

from cli.auth.session_manager import create_session_manager
from cli.utils.url_utils import get_api_endpoint

console = Console()
logger = logging.getLogger("hivekit")


class AuthenticationError(Exception):
    """
    Raised when authentication fails and cannot be recovered automatically.
    """


class HttpClient:
    """
    HTTP client for communicating with the Hive backend server.
    """

    def __init__(
        self,
        base_url: str,
        on_auth_failure: Callable[[], requests.Session],
        session: requests.Session,
        insecure: bool = False,
    ) -> None:
        """
        Initialize the HTTP client.

        Args:
            base_url: Base URL of the backend server.
            on_auth_failure: Callback invoked on 401 responses. Should attempt
                re-authentication and return a new session.
            session: Pre-configured HTTP session for making requests.
            insecure: If True, disable SSL certificate verification on all requests.
        """
        self.base_url = base_url.rstrip("/")
        self._session = session
        self._on_auth_failure = on_auth_failure
        self._insecure = insecure

    def create_experiment(self, experiment_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new experiment.

        Args:
            experiment_data: Experiment CRD data to send.

        Returns:
            Created experiment data from the server.
        """
        url = f"{self.base_url}/experiments"
        headers = self._get_headers()

        try:
            response = self._request(method="post", url=url, headers=headers, json=experiment_data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            error_msg = f"Failed to create experiment: {e}"
            if e.response is not None:
                try:
                    error_detail = e.response.json()
                    if "error" in error_detail:
                        error_msg = f"Failed to create experiment: {error_detail['error']}"
                except Exception:
                    error_msg = f"Failed to create experiment: {e.response.text}"
            raise Exception(error_msg) from e
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to connect to backend server at {url}: {e}") from e

    def get_experiment(self, name: str) -> Dict[str, Any]:
        """
        Get an experiment by name.

        Args:
            name: Experiment name.

        Returns:
            Experiment data from the server.
        """
        url = f"{self.base_url}/experiments/{name}"
        headers = self._get_headers()

        try:
            response = self._request(method="get", url=url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to get experiment: {e}") from e

    def list_experiments(self) -> Dict[str, Any]:
        """
        List experiments.

        Returns:
            List of experiments from the server.
        """
        url = f"{self.base_url}/experiments"
        headers = self._get_headers()

        try:
            response = self._request(method="get", url=url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to list experiments: {e}") from e

    def delete_experiment(self, name: str) -> Dict[str, Any]:
        """
        Delete an experiment.

        Args:
            name: Experiment name.

        Returns:
            Response from the server.
        """
        url = f"{self.base_url}/experiments/{name}"
        headers = self._get_headers()

        try:
            response = self._request(method="delete", url=url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to delete experiment: {e}") from e

    def delete_experiments_batch(self, names: list[str]) -> Dict[str, Dict[str, Any]]:
        """
        Delete multiple experiments in batch.

        Args:
            names: List of experiment names to delete.

        Returns:
            Dictionary mapping experiment names to their deletion results.
            Each result contains either 'success' or 'error' key.
        """
        results = {}
        for name in names:
            try:
                # TODO: Consider implementing a batch delete endpoint in the backend to optimize this
                response = self.delete_experiment(name)
                results[name] = {"success": True, "response": response}
            except Exception as e:
                results[name] = {"success": False, "error": str(e)}
        return results

    def _get_headers(self) -> Dict[str, str]:
        """
        Get common headers for all requests.
        """
        return {"Content-Type": "application/json"}

    def _request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        json: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """
        Make an HTTP request, automatically retrying once on 401 by invoking
        the on_auth_failure callback.
        """
        try:
            response = self._session.request(
                method=method,
                url=url,
                headers=headers,
                json=json,
                timeout=30,
                verify=not self._insecure,
            )
        except OAuthError as e:
            logger.debug(f"OAuth error during request: {e.error}. Attempting to re-authenticate.")
            return self._retry_with_reauth(method=method, url=url, headers=headers, json=json)
        if response.status_code == HTTPStatus.UNAUTHORIZED:
            logger.debug("Received 401 response. Attempting to re-authenticate.")
            return self._retry_with_reauth(method=method, url=url, headers=headers, json=json)
        return response

    def _retry_with_reauth(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        json: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """
        Attempt re-authentication and retry the failed request.
        """
        try:
            self._session = self._on_auth_failure()
        except AuthenticationError:
            raise
        except Exception as e:
            raise AuthenticationError(
                "Your credentials have expired. Please run 'hive login' to re-authenticate."
            ) from e
        response = self._session.request(
            method=method,
            url=url,
            headers=headers,
            json=json,
            timeout=30,
            verify=not self._insecure,
        )
        if response.status_code == HTTPStatus.UNAUTHORIZED:
            raise AuthenticationError(
                "Your credentials have expired. Please run 'hive login' to re-authenticate."
            )
        return response


def create_http_client(
    organization_id: Optional[str] = None,
    no_auth: bool = False,
    insecure: bool = False,
) -> HttpClient:
    """
    Create an HttpClient, setting up OIDC authentication if needed.

    When authentication is enabled (no_auth=False), the organization_id is
    required. If it is not provided, an AuthenticationError is raised.

    Args:
        organization_id: The organization ID for authentication. Required when
            no_auth is False.
        no_auth: If True, skip authentication entirely. Defaults to False.
        insecure: If True, disable SSL certificate verification. Defaults to False.

    Returns:
        A configured HttpClient instance.

    Raises:
        AuthenticationError: If authentication is required but no organization
            ID is provided, or if no stored token is available.
    """
    base_url = get_api_endpoint()
    if no_auth:
        on_auth_failure = _raise_not_configured
        session = requests.Session()
    else:
        if organization_id is None:
            raise AuthenticationError(
                "No organization ID configured. Please run 'hive init' to set up "
                "your configuration."
            )
        session_manager = create_session_manager(
            organization_id=organization_id,
            base_url=base_url,
            insecure=insecure,
        )
        on_auth_failure = session_manager.login
        session = session_manager.create_session()
    return HttpClient(
        base_url=base_url,
        on_auth_failure=on_auth_failure,
        session=session,
        insecure=insecure,
    )


def _raise_not_configured() -> requests.Session:
    """
    Callback for unauthenticated clients that raises an error on 401.
    """
    raise AuthenticationError(
        "Authentication is not configured. Please run 'hive login' to authenticate."
    )
