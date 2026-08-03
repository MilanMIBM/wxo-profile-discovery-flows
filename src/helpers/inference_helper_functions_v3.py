# ================================================================================================================================================================
# Inference Helper Functions developed for the EMEA - IBM Build Engineering team by Milan Mrdenovic (milan.mrdenovic@ibm.com)
# Version: 1.3
# Date: 13.05.2026
# License: Apache 2.0 - https://www.apache.org/licenses/LICENSE-2.0
# Supported providers - IBM watsonx.ai, IBM watsonx.orchestrate , Red Hat AI inference on IBM Cloud, OpenAI SDK compatible providers, IBM Consulting Advantage
# ================================================================================================================================================================
# Libraries: ibm-watsonx-ai, ibm-cloud-sdk-core, openai, certifi, requests

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
import requests
import certifi


class InferenceClient:
    """
    Unified inference client wrapping any supported provider.

    Supported providers - IBM watsonx.ai, IBM watsonx.orchestrate, Red Hat AI
    inference on IBM Cloud, OpenAI SDK compatible providers, IBM Consulting
    Advantage.

    Construct via the ``__init__`` (which initialises the underlying provider
    client) and then call the instance methods, e.g.::

        inf = InferenceClient(
            provider="watsonx",
            api_key=WX_API_KEY,
            url=WX_URL,
            project_id=PROJECT_ID,
            model_id="ibm/granite-3-8b-instruct",
        )
        models = inf.get_models()
        results = inf.run_iterative_inference(messages, number_of_iterations=3)

    Switching models / agents
    -------------------------
    The model (or WXO agent) does NOT have to be supplied up front. You can:

    - pass ``model_id`` / ``agent_id`` to ``__init__`` (the default for all calls),
    - switch the default later with ``set_model(...)`` / ``set_agent(...)``,
    - or override per call by passing ``model_id`` / ``agent_id`` directly to
    ``run_chat_inference`` / ``run_iterative_inference``.

    Example::

        inf = InferenceClient(provider="ica", api_key=ICA_API_KEY)  # no model up front
        inf.set_model(inf.get_models()[0])                          # pick one later
        inf.run_chat_inference(messages)                            # uses it
        inf.run_chat_inference(messages, model_id="other-model")    # one-off override

    Unified ``url`` parameter
    -------------------------
    A single ``url`` parameter replaces the old per-provider URL arguments. Its
    meaning depends on the provider (see ``__init__``). The legacy ``base_url``
    and ``instance_url`` keyword arguments are still accepted as aliases.

    Progress bars
    -------------
    ``run_iterative_inference`` and ``run_batch_inference`` show a marimo
    progress bar by default. Toggle the default with ``progress_bar`` on
    ``__init__``, or override per call with the ``progress_bar`` argument. When
    marimo is not installed (or not running in a marimo context) the bar is
    silently skipped and the loops behave identically.

    The provider client created during initialisation is stored on
    ``self.client`` and used implicitly by all methods. ``self.provider`` and
    ``self.model_id`` / ``self.agent_id`` act as defaults that individual method
    calls may override.
    """

    # Valid WXO tool binding types, per the /tools schema (ToolBinding object).
    # Each tool's ``binding`` carries exactly one of these keys.
    WXO_TOOL_BINDING_TYPES = (
        "openapi",
        "python",
        "wxflows",
        "skill",
        "client_side",
        "conversational_search",
        "mcp",
        "flow",
        "langflow",
    )

    # ---------------------------------------------------------------------------
    # Client initialisation
    # ---------------------------------------------------------------------------

    def __init__(
        self,
        provider: str,
        api_key: str,
        # unified service/base/instance URL (meaning depends on provider)
        url: str = "",
        # watsonx
        project_id: str = "",
        space_id: str = "",
        model_id: str = "",
        params: Optional[Dict[str, Any]] = None,
        # rhai (builds url from these if url not given)
        project: str = "",
        region: str = "us-east",
        # wxo
        auth_type: str = "ibm_iam",
        is_local: bool = False,
        api_version: str = "v1",
        agent_id: Optional[str] = None,
        # progress
        progress_bar: bool = True,
        # legacy aliases for `url` (kept for backwards compatibility)
        base_url: str = "",
        instance_url: str = "",
        **kwargs: Any,
    ):
        """
        Initialise an inference client for any supported provider.

        Parameters
        ----------
        provider:
            One of "watsonx", "openai", "rhai", "wxo", "ica".
        api_key:
            IBM Cloud API key shared across all IBM providers (WX_API_KEY /
            IBM_CLOUD_API_KEY / WXO_API_KEY). For ICA pass ICA_API_KEY. For
            generic OpenAI endpoints pass the endpoint-specific key here.
        url:
            Unified endpoint URL. Its meaning depends on the provider:
                - watsonx: watsonx.ai service URL.
                - openai:  full OpenAI-compatible base URL.
                - rhai:    OpenAI-compatible base URL. If omitted, it is built
                        automatically from ``project`` + ``region``.
                - ica:     OpenAI-compatible base URL. Defaults to
                        https://api.nextgen-beta.ica.ibm.com/ica/v1/chat-models
                        if omitted; override via ICA_BASE_URL env var.
                - wxo:     WXO service-instance URL.
            The legacy ``base_url`` (openai/rhai/ica) and ``instance_url`` (wxo)
            keyword arguments are still accepted and, if given, populate ``url``.

        watsonx-specific
        ----------------
        project_id: Watson Studio project ID (takes precedence over space_id).
        space_id:   Watson Studio deployment space ID.
        model_id:   Model to wrap in a ModelInference object.
        params:     Generation params passed to ModelInference.

        openai / rhai / ica-specific
        ----------------------------
        project:    RHAI project ID (rhai only; used to build ``url``).
        region:     RHAI region, default "us-east" (rhai only).

        wxo-specific
        ------------
        auth_type:    One of:
                        "ibm_iam" (default) - IBM Cloud
                        "cpd" - IBM watsonx orchestrate software (cloud pak for data),
                        "mcsp",
                        "mcsp_v2"
        is_local:     True when targeting a local Developer Edition server.
        api_version:  WXO API version, default "v1".
        agent_id:     Default WXO agent ID used by chat / iterative methods.

        model / agent (optional)
        -------------------------
        model_id / agent_id are optional up front. They can be set later via
        ``set_model`` / ``set_agent`` or overridden per call. See the class
        docstring.

        progress_bar:
            Whether to show a marimo progress bar while iterating in
            ``run_iterative_inference`` / ``run_batch_inference``. Defaults to
            True. This is the instance default; each call accepts a
            ``progress_bar`` argument to override it. Silently ignored when
            marimo is not installed or not running in a marimo context.

        Notes
        -----
        After construction ``self.client`` holds:
        - watsonx:       ibm_watsonx_ai.foundation_models.ModelInference (when model_id given)
                        or ibm_watsonx_ai.APIClient (when model_id omitted).
        - openai / rhai / ica: openai.OpenAI client instance.
        - wxo:           dict {"base_url": str, "headers": dict} for REST calls.
        - None if required credentials are missing.
        """
        # Collapse the legacy URL aliases into the single `url` parameter.
        url = url or base_url or instance_url

        self.provider = provider.strip().lower()
        self.api_key = api_key
        self.url = url
        self.model_id = model_id or None
        self.agent_id = agent_id
        self.params = params or {}
        self.progress_bar = progress_bar
        self.client = self._initialize_client(
            provider=self.provider,
            api_key=api_key,
            url=url,
            project_id=project_id,
            space_id=space_id,
            model_id=model_id,
            params=params,
            project=project,
            region=region,
            auth_type=auth_type,
            is_local=is_local,
            api_version=api_version,
            **kwargs,
        )

    # ---------------------------------------------------------------------------
    # Model / agent selection
    # ---------------------------------------------------------------------------

    def set_model(self, model_id: Optional[str]) -> "InferenceClient":
        """
        Set the default model used by subsequent chat / iterative calls.

        For the watsonx provider the underlying ModelInference object is rebuilt
        so the new model takes effect; for openai / rhai / ica the model is simply
        passed per request, so no rebuild is needed.

        Returns ``self`` to allow chaining.
        """
        self.model_id = model_id or None

        if self.provider == "watsonx" and self.model_id:
            # watsonx binds the model into the client object, so re-create it.
            from ibm_watsonx_ai.foundation_models import ModelInference

            api_client = getattr(self.client, "_client", None) or getattr(
                self.client, "api_client", None
            )
            if api_client is not None:
                self.client = ModelInference(
                    api_client=api_client,
                    model_id=self.model_id,
                    params=self.params or {},
                )
            else:
                print(
                    "set_model (watsonx): could not access the underlying APIClient "
                    "to rebind the model. Re-initialise the client with the new "
                    "model_id instead."
                )
        return self

    def set_agent(self, agent_id: Optional[str]) -> "InferenceClient":
        """
        Set the default WXO agent used by subsequent chat / iterative calls.

        Returns ``self`` to allow chaining.
        """
        self.agent_id = agent_id
        return self

    # ---------------------------------------------------------------------------
    # Progress bar helper
    # ---------------------------------------------------------------------------

    def _progress_iter(
        self,
        collection,
        enabled: Optional[bool],
        total: Optional[int] = None,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
    ):
        """
        Wrap ``collection`` in a marimo progress bar when enabled, else return it
        unchanged.

        ``enabled`` overrides the instance ``self.progress_bar`` default when not
        None. Falls back to the bare collection if marimo is unavailable, so the
        loop works identically outside a marimo notebook.
        """
        show = self.progress_bar if enabled is None else enabled
        if not show:
            return collection
        try:
            import marimo as mo

            return mo.status.progress_bar(
                collection,
                total=total,
                title=title,
                subtitle=subtitle,
                remove_on_exit=True,
            )
        except Exception:
            # marimo not installed / not in a marimo context - degrade silently.
            return collection

    def _progress_bar_cm(
        self,
        enabled: Optional[bool],
        total: Optional[int] = None,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
    ):
        """
        Return a context manager yielding an ``update()`` callable for a marimo
        progress bar.

        Use this when the loop may terminate early (so a plain iterating bar
        cannot be used). ``enabled`` overrides ``self.progress_bar`` when not
        None. When the bar is disabled or marimo is unavailable, yields a no-op
        ``update`` so call sites stay identical.
        """
        from contextlib import contextmanager

        show = self.progress_bar if enabled is None else enabled

        @contextmanager
        def _noop():
            yield lambda *a, **k: None

        if not show:
            return _noop()

        try:
            import marimo as mo
        except Exception:
            return _noop()

        @contextmanager
        def _bar():
            try:
                with mo.status.progress_bar(
                    total=total,
                    title=title,
                    subtitle=subtitle,
                    remove_on_exit=True,
                ) as pb:
                    yield pb.update
            except Exception:
                # Not in a marimo context (or API mismatch) - degrade to no-op.
                yield lambda *a, **k: None

        return _bar()

    @staticmethod
    def _initialize_client(
        provider: str,
        api_key: str,
        url: str = "",
        project_id: str = "",
        space_id: str = "",
        model_id: str = "",
        params: Optional[Dict[str, Any]] = None,
        project: str = "",
        region: str = "us-east",
        auth_type: str = "ibm_iam",
        is_local: bool = False,
        api_version: str = "v1",
        **kwargs: Any,
    ):
        """Build and return the underlying provider client (see __init__).

        ``url`` is the unified endpoint: the watsonx service URL, the
        openai/rhai/ica base URL, or the wxo instance URL depending on provider.
        """
        provider = provider.strip().lower()

        if provider == "ica":
            if not api_key:
                print("InferenceClient (ica): api_key is required. Returning None.")
                return None
            _base_url = url or "https://api.nextgen-beta.ica.ibm.com/ica/v1/chat-models"
            from openai import OpenAI

            client = OpenAI(api_key=api_key, base_url=_base_url, **kwargs)
            print(f"ICA client initialised with base_url: {_base_url}")
            return client

        if provider == "watsonx":
            if not (api_key and url and (project_id or space_id)):
                print(
                    "InferenceClient (watsonx): api_key, url, and either "
                    "project_id or space_id are required. Returning None."
                )
                return None

            from ibm_watsonx_ai import Credentials, APIClient

            credentials = Credentials(url=url, api_key=api_key)
            client = APIClient(credentials, **kwargs)

            if project_id:
                client.set.default_project(project_id)
                print(f"watsonx.ai client set to Project: {project_id}")
            else:
                client.set.default_space(space_id)
                print(f"watsonx.ai client set to Deployment Space: {space_id}")

            if model_id:
                from ibm_watsonx_ai.foundation_models import ModelInference

                return ModelInference(
                    api_client=client,
                    model_id=model_id,
                    params=params or {},
                )

            return client

        if provider in ("openai", "rhai"):
            if provider == "rhai" and not url:
                if not (api_key and project):
                    print(
                        "InferenceClient (rhai): api_key and project are "
                        "required. Returning None."
                    )
                    return None
                url = f"https://{region}.rhai.ibm.com/v1/projects/{project}/inference"

            if not (api_key and url):
                print(
                    f"InferenceClient ({provider}): api_key and url "
                    "are required. Returning None."
                )
                return None

            from openai import OpenAI

            client = OpenAI(api_key=api_key, base_url=url, **kwargs)
            print(f"{provider} client initialised with base_url: {url}")
            return client

        if provider == "wxo":
            if not (api_key and url):
                print(
                    "InferenceClient (wxo): api_key and url (instance URL) are "
                    "required. Returning None."
                )
                return None

            token = InferenceClient.get_wxo_token(
                api_key=api_key,
                instance_url=url,
                auth_type=auth_type,
            )
            meta = InferenceClient.build_wxo_call_meta(
                instance_url=url,
                token=token,
                is_local=is_local,
                api_version=api_version,
            )
            meta["headers"]["Content-Type"] = "application/json"
            print(f"WXO client initialised - base_url: {meta['base_url']}")
            return meta

        print(f"InferenceClient: unknown provider '{provider}'. Returning None.")
        return None

    # ---------------------------------------------------------------------------
    # WXO authentication (inlined from auth_helper_functions)
    # ---------------------------------------------------------------------------

    @staticmethod
    def generate_zen_auth_header(username, api_key):
        """Generate a Zen API authorization header.

        Args:
            username: Zen username
            api_key: Zen API key

        Returns:
            str: Authorization header value in format "ZenApiKey <encoded_credentials>"
        """
        import base64

        credentials = f"{username}:{api_key}"
        encoded = base64.b64encode(credentials.encode()).decode()

        return f"ZenApiKey {encoded}"

    @staticmethod
    def get_wxo_token(
        api_key: str,
        instance_url: str = None,
        auth_type: str = "ibm_iam",
        iam_url: str = None,
        username: str = None,
        password: str = None,
    ) -> str:
        """Get a WXO bearer token, mirroring the ADK CLI auth flow.

        Corresponds to:
            orchestrate env add -n <name> -u <instance_url> --type <auth_type>
            orchestrate env activate <name> --api-key <api_key>

        Auth types:
            "ibm_iam"  (default) - IBM Cloud IAM; for .cloud.ibm.com instances.
            "mcsp"               - MCSP v1, falls back to v2; for orchestrate.ibm.com instances.
            "mcsp_v2"            - MCSP v2 explicit; requires instance_url with "instances/<id>".
            "cpd"                - Cloud Pak for Data (on-prem); requires username + api_key or password.

        Args:
            api_key:       WXO / IBM Cloud API key (--api-key).
            instance_url:  WXO service-instance URL (--url). Required for mcsp_v2 and cpd.
            auth_type:     One of "ibm_iam", "mcsp", "mcsp_v2", "cpd". Defaults to "ibm_iam".
            iam_url:       Optional override for the IAM/auth endpoint.
            username:      CPD username (cpd only).
            password:      CPD password (cpd only; mutually exclusive with api_key).

        Returns:
            str: Raw JWT access token (no "Bearer " prefix).

        Raises:
            ValueError: On invalid auth_type or missing required arguments.
        """
        auth_type = auth_type.lower()

        if auth_type == "ibm_iam":
            from ibm_cloud_sdk_core.authenticators import IAMAuthenticator

            kwargs = {"apikey": api_key}
            if iam_url:
                kwargs["url"] = iam_url
            authenticator = IAMAuthenticator(**kwargs)
            return authenticator.token_manager.get_token()

        elif auth_type == "mcsp":
            from ibm_cloud_sdk_core.authenticators import (
                MCSPAuthenticator,
                MCSPV2Authenticator,
            )

            try:
                url = iam_url or "https://iam.platform.saas.ibm.com"
                authenticator = MCSPAuthenticator(apikey=api_key, url=url)
                return authenticator.token_manager.get_token()
            except Exception:
                url = iam_url or "https://account-iam.platform.saas.ibm.com"
                instance_id = instance_url.split("instances/")[1]
                authenticator = MCSPV2Authenticator(
                    apikey=api_key,
                    url=url,
                    scope_collection_type="services",
                    scope_id=instance_id,
                )
                return authenticator.token_manager.get_token()

        elif auth_type == "mcsp_v2":
            from ibm_cloud_sdk_core.authenticators import MCSPV2Authenticator

            if not instance_url:
                raise ValueError("instance_url is required for mcsp_v2 auth.")
            url = iam_url or "https://account-iam.platform.saas.ibm.com"
            instance_id = instance_url.split("instances/")[1]
            authenticator = MCSPV2Authenticator(
                apikey=api_key,
                url=url,
                scope_collection_type="services",
                scope_id=instance_id,
            )
            return authenticator.token_manager.get_token()

        elif auth_type == "cpd":
            from ibm_cloud_sdk_core.authenticators import CloudPakForDataAuthenticator

            if not instance_url:
                raise ValueError("instance_url is required for cpd auth.")
            if not username:
                raise ValueError("username is required for cpd auth.")
            if api_key and password:
                raise ValueError(
                    "Provide either api_key or password for cpd auth, not both."
                )
            if not api_key and not password:
                raise ValueError("Either api_key or password is required for cpd auth.")
            cpd_iam_url = (
                iam_url or f"{instance_url.split('/orchestrate')[0]}/icp4d-api"
            )
            authenticator = CloudPakForDataAuthenticator(
                username=username,
                password=password or None,
                apikey=api_key or None,
                url=cpd_iam_url,
                disable_ssl_verification=True,
            )
            return authenticator.token_manager.get_token()

        else:
            raise ValueError(
                f"Unsupported auth_type '{auth_type}'. Choose from: ibm_iam, mcsp, mcsp_v2, cpd."
            )

    @staticmethod
    def build_wxo_call_meta(
        instance_url: str,
        token: str = None,
        is_local: bool = False,
        api_version: str = "v1",
        append_orchestrate: bool = True,
        is_onprem: bool = False,
        onprem_host: str = None,
        onprem_port: str = None,
        onprem_namespace: str = None,
        onprem_instance_id: str = None,
        zen_username: str = None,
        zen_api_key: str = None,
    ) -> dict:
        """Build the base URL and Authorization header for WXO REST calls.

        Mirrors the ADK's BaseAPIClient setup: appends "/v1/orchestrate" for remote
        instances or "/v1" for local Developer Edition servers, and formats the
        bearer token header.

        For on-premises deployments, the base URL is constructed as:
            https://{onprem_host}:{port}/orchestrate/{namespace}/instances/{instanceid}/v1
        and the Authorization header uses the Zen API key scheme.

        Args:
            instance_url:        WXO service-instance URL (trailing slash stripped).
                                Not used when is_onprem=True.
            token:               Raw JWT bearer token from get_wxo_token(). Not used
                                when is_onprem=True (Zen API key is used instead).
            is_local:            True when targeting a local Developer Edition server
                                (localhost / 127.0.0.1 / etc.).
            api_version:         Version of the API (currently v1 or v2) for different calls.
            append_orchestrate:  When True (default), appends "/orchestrate" to the base URL
                                for remote instances. Set to False for endpoints that do not
                                use the /orchestrate path segment. Ignored when is_onprem=True.
            is_onprem:           True when targeting an on-premises IBM Software Hub deployment.
                                When True, onprem_host, onprem_namespace, onprem_instance_id,
                                zen_username, and zen_api_key are required.
            onprem_host:         Hostname or IP of the IBM Software Hub cluster
                                (e.g. "api.example.com" or "cpd.example.com:31843").
            onprem_port:         Optional port number. Can also be embedded in onprem_host.
            onprem_namespace:    Namespace where the WXO instance is deployed.
            onprem_instance_id:  Unique identifier of the WXO instance (the number after
                                "orchestrate-" in the instance details URL).
            zen_username:        IBM Software Hub username for Zen API key encoding.
            zen_api_key:         IBM Software Hub API key for Zen API key encoding.

        Returns:
            dict with keys:
                "base_url" - versioned API base URL (str)
                "headers"  - {"Authorization": "Bearer <token>"} or
                            {"Authorization": "ZenApiKey <encoded>"} (dict)

        Raises:
            ValueError: When is_onprem=True and required on-prem arguments are missing,
                        or when is_onprem=False and token is not provided.
        """
        if is_onprem:
            if not all(
                [
                    onprem_host,
                    onprem_namespace,
                    onprem_instance_id,
                    zen_username,
                    zen_api_key,
                ]
            ):
                raise ValueError(
                    "is_onprem=True requires: onprem_host, onprem_namespace, "
                    "onprem_instance_id, zen_username, and zen_api_key."
                )
            host = onprem_host.rstrip("/")
            if onprem_port and ":" not in host:
                host = f"{host}:{onprem_port}"
            base_url = (
                f"https://{host}/orchestrate/{onprem_namespace}"
                f"/instances/{onprem_instance_id}/{api_version}"
            )
            auth_header = InferenceClient.generate_zen_auth_header(
                zen_username, zen_api_key
            )
            return {
                "base_url": base_url,
                "headers": {"Authorization": auth_header},
            }

        if token is None:
            raise ValueError("token is required when is_onprem=False.")

        base = instance_url.rstrip("/")
        if is_local or not append_orchestrate:
            base_url = f"{base}/{api_version}"
        else:
            base_url = f"{base}/{api_version}/orchestrate"
        return {
            "base_url": base_url,
            "headers": {"Authorization": f"Bearer {token}"},
        }

    # ---------------------------------------------------------------------------
    # Model / agent listing
    # ---------------------------------------------------------------------------

    def get_models(
        self,
        provider: Optional[str] = None,
    ) -> List[str]:
        """
        Return available model IDs for the active provider.

        For ICA, use get_ica_models() instead if you need the creditless /
        consumptive split.

        Parameters
        ----------
        provider:
            Override the instance provider for this call. One of "watsonx",
            "openai", "rhai", "wxo", "ica".

        Returns
        -------
        List of model ID strings, empty list on failure or missing client.
        """
        client = self.client
        if client is None:
            return []

        provider = (provider or self.provider).strip().lower()

        try:
            if provider == "watsonx":
                import pandas as pd

                specs = client.foundation_models.get_chat_function_calling_model_specs()
                return pd.DataFrame(specs.get("resources", [])).model_id.to_list()

            if provider in ("openai", "rhai", "ica"):
                return [m.id for m in client.models.list().data]

            if provider == "wxo":
                url = f"{client['base_url']}/models/list"
                response = requests.get(
                    url, headers=client["headers"], verify=certifi.where()
                )
                response.raise_for_status()
                resources = response.json().get("resources", [])
                return [m["id"] for m in resources if m.get("id")]

        except Exception as e:
            print(f"get_models ({provider}) error: {e}")

        return []

    def get_ica_models(self) -> Dict[str, List[str]]:
        """
        Return ICA model lists split by cost tier.

        Returns
        -------
        Dict with keys:
            "all"         - every model except advantage_assist
            "creditless"  - models with x_ica_info.cost_tier == "0x"
            "consumptive" - all minus creditless
        """
        ica_client = self.client
        if ica_client is None:
            return {"all": [], "creditless": [], "consumptive": []}
        try:
            import pandas as pd

            data = ica_client.models.list().to_dict().get("data", [])
            df = pd.json_normalize(data)
            all_models = sorted(
                df.query("id != 'advantage_assist.advantage-assist'")["id"].tolist()
            )
            creditless = sorted(
                df.query(
                    "id != 'advantage_assist.advantage-assist' and `x_ica_info.cost_tier` == '0x'"
                )["id"].tolist()
            )
            consumptive = sorted([m for m in all_models if m not in creditless])
            return {
                "all": all_models,
                "creditless": creditless,
                "consumptive": consumptive,
            }
        except Exception as e:
            print(f"get_ica_models error: {e}")
            return {"all": [], "creditless": [], "consumptive": []}

    def get_wxo_agents(self) -> Dict[str, str]:
        """
        Return a {display_name: agent_id} mapping of agents in the WXO instance.

        Uses GET /v2/orchestrate/agents (separate from the v1 base_url).
        """
        wxo_client = self.client
        if not wxo_client:
            return {}
        try:
            url = f"{wxo_client['base_url']}/agents"
            response = requests.get(
                url, headers=wxo_client["headers"], verify=certifi.where()
            )
            response.raise_for_status()
            agents = response.json()
            if isinstance(agents, dict):
                agents = agents.get("resources", []) or []
            return {
                a.get("display_name") or a.get("name") or a.get("id", ""): a.get(
                    "id", ""
                )
                for a in agents
                if a.get("id")
            }
        except Exception as e:
            print(f"get_wxo_agents error: {e}")
            return {}

    def get_wxo_flows(
        self,
        flow_id: Optional[str] = None,
        version: Optional[str] = None,
        state: Optional[str] = None,
        instance_id: Optional[str] = None,
        root_only: bool = True,
        initiators: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Return a list of flow instances from the WXO instance.

        Uses GET /v1/orchestrate/flows (relative to the versioned base_url, which
        already includes the "/orchestrate" segment for remote instances).

        Parameters
        ----------
        flow_id:
            Filter to a single flow ID.
        version:
            Filter to a specific flow version.
        state:
            Filter by instance state. One of "completed", "in_progress",
            "interrupted", "failed".
        instance_id:
            Filter to a single instance ID.
        root_only:
            When True (default), return only root flow instances.
        initiators:
            Optional list of initiator IDs to filter by.
        page:
            1-based page number (default 1).
        page_size:
            Number of instances per page (default 20).

        Returns
        -------
        List of flow-instance dicts, empty list on failure or missing client.
        """
        wxo_client = self.client
        if not wxo_client:
            return []
        try:
            url = f"{wxo_client['base_url']}/flows"
            params: Dict[str, Any] = {
                "root_only": root_only,
                "page": page,
                "page_size": page_size,
            }
            if flow_id is not None:
                params["flow_id"] = flow_id
            if version is not None:
                params["version"] = version
            if state is not None:
                params["state"] = state
            if instance_id is not None:
                params["instance_id"] = instance_id
            if initiators is not None:
                params["initiators"] = initiators

            response = requests.get(
                url,
                headers=wxo_client["headers"],
                params=params,
                verify=certifi.where(),
            )
            response.raise_for_status()
            flows = response.json()
            if isinstance(flows, dict):
                flows = flows.get("resources", flows.get("flows", [])) or []
            return flows
        except Exception as e:
            print(f"get_wxo_flows error: {e}")
            return []

    def get_wxo_tools(
        self,
        ids: Optional[List[str]] = None,
        names: Optional[List[str]] = None,
        show_bundled: bool = False,
        tool_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return a list of tools from the WXO instance.

        Uses GET /v1/orchestrate/tools (relative to the versioned base_url, which
        already includes the "/orchestrate" segment for remote instances).

        Parameters
        ----------
        ids:
            Optional list of tool IDs to filter by.
        names:
            Optional list of tool names to filter by.
        show_bundled:
            When True, include bundled tools (default False).
        tool_types:
            Optional list of tool (binding) type names to include, e.g.
            ["mcp", "openapi", "flow", "python"]. Valid values are the binding
            types defined by the /tools schema (see
            ``InferenceClient.WXO_TOOL_BINDING_TYPES``): openapi, python,
            wxflows, skill, client_side, conversational_search, mcp, flow,
            langflow. Only tools whose ``binding`` contains at least one of the
            requested keys are returned. Matching is case-insensitive.
            Unrecognised values are ignored (with a warning). Applied
            client-side after the response is fetched (tool type is not a
            server-side query param). When None, tools are not filtered by type.

        Returns
        -------
        List of tool dicts, empty list on failure or missing client.
        """
        wxo_client = self.client
        if not wxo_client:
            return []

        # Guard against a common mix-up: passing a tool (binding) type name in
        # ``ids``. The ``ids`` query param expects tool UUIDs; sending a value
        # like "flow" makes the server return HTTP 500. Any non-UUID entries in
        # ``ids`` are pulled out and routed to the client-side tool_types filter
        # instead, so the caller's intent still works.
        import uuid

        def _is_uuid(value: str) -> bool:
            try:
                uuid.UUID(str(value))
                return True
            except (ValueError, AttributeError, TypeError):
                return False

        tool_types = list(tool_types) if tool_types else []
        if ids is not None:
            real_ids = [i for i in ids if _is_uuid(i)]
            misrouted = [i for i in ids if not _is_uuid(i)]
            if misrouted:
                print(
                    f"get_wxo_tools: ids expects tool UUIDs; treating non-UUID "
                    f"value(s) {misrouted} as tool_types instead."
                )
                tool_types.extend(misrouted)
            ids = real_ids or None
        tool_types = tool_types or None

        try:
            url = f"{wxo_client['base_url']}/tools"
            # requests serializes Python bools as "True"/"False"; send the
            # lowercase JSON form the server expects.
            params: Dict[str, Any] = {"show_bundled": str(show_bundled).lower()}
            if ids is not None:
                params["ids"] = ids
            if names is not None:
                params["names"] = names

            response = requests.get(
                url,
                headers=wxo_client["headers"],
                params=params,
                verify=certifi.where(),
            )
            response.raise_for_status()
            tools = response.json()
            if isinstance(tools, dict):
                tools = tools.get("resources", tools.get("tools", [])) or []

            if tool_types is not None:
                wanted = {b.strip().lower() for b in tool_types}
                valid = set(self.WXO_TOOL_BINDING_TYPES)
                unknown = wanted - valid
                if unknown:
                    print(
                        f"get_wxo_tools: ignoring unknown tool_types "
                        f"{sorted(unknown)}. Valid types: "
                        f"{sorted(valid)}."
                    )
                wanted &= valid
                tools = [
                    t
                    for t in tools
                    if isinstance(t.get("binding"), dict)
                    and any(
                        k.lower() in wanted and t["binding"][k] is not None
                        for k in t["binding"]
                    )
                ]
            return tools
        except Exception as e:
            print(f"get_wxo_tools error: {e}")
            return []

    def get_wxo_tool_by_id(self, tool_id: str) -> Optional[Dict[str, Any]]:
        """
        Return a single tool from the WXO instance by its ID.

        Uses GET /v1/orchestrate/tools/{id} (relative to the versioned base_url,
        which already includes the "/orchestrate" segment for remote instances).

        Parameters
        ----------
        tool_id:
            The tool ID to fetch (required).

        Returns
        -------
        The tool dict on success, None on failure or missing client.
        """
        wxo_client = self.client
        if not wxo_client:
            return None
        if not tool_id:
            print("get_wxo_tool_by_id: tool_id is required")
            return None
        try:
            url = f"{wxo_client['base_url']}/tools/{tool_id}"
            response = requests.get(
                url, headers=wxo_client["headers"], verify=certifi.where()
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"get_wxo_tool_by_id error: {e}")
            return None

    # ---------------------------------------------------------------------------
    # Unified single-turn chat
    # ---------------------------------------------------------------------------

    def run_chat_inference(
        self,
        messages: List[Dict[str, str]],
        provider: Optional[str] = None,
        model_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Run a single chat inference call and return a normalised response dict.

        All providers are normalised to the OpenAI chat-completions shape:
            {"choices": [{"message": {"role": ..., "content": ...}}], "usage": {...}}

        Parameters
        ----------
        messages:
            List of {"role": ..., "content": ...} dicts.
        provider:
            Override the instance provider. One of "watsonx", "openai", "rhai",
            "wxo", "ica".
        model_id:
            Required for openai / rhai / ica; used for wxo when no agent_id is
            given. Defaults to the instance model_id.
        params:
            Extra generation params forwarded to the provider. Defaults to the
            instance params.
        agent_id:
            WXO agent ID (wxo provider only). Takes precedence over model_id.
            Defaults to the instance agent_id.
        """
        client = self.client
        if client is None or not messages:
            return None

        provider = (provider or self.provider).strip().lower()
        model_id = model_id if model_id is not None else self.model_id
        agent_id = agent_id if agent_id is not None else self.agent_id
        params = params if params is not None else self.params
        params = params or {}

        try:
            if provider == "watsonx":
                return client.chat(messages=messages, **kwargs)

            if provider == "wxo":
                base_url = client["base_url"]
                headers = client["headers"]

                if not agent_id:
                    raise ValueError("run_chat_inference (wxo): agent_id is required")
                # POST /v1/orchestrate/{agent_id}/chat/completions
                url = f"{base_url}/{agent_id}/chat/completions"
                payload: Dict[str, Any] = {
                    "messages": messages,
                    "stream": False,
                    **params,
                    **kwargs,
                }
                response = requests.post(
                    url, headers=headers, json=payload, verify=certifi.where()
                )
                response.raise_for_status()
                return response.json()

            # OpenAI-compatible path (openai, rhai, ica)
            if model_id is None:
                raise ValueError(
                    f"run_chat_inference ({provider}): model_id is required"
                )

            extra = {k: v for k, v in params.items() if k != "model_id"}
            response = client.chat.completions.create(
                model=model_id,
                messages=messages,
                **extra,
                **kwargs,
            )
            return (
                response.model_dump()
                if hasattr(response, "model_dump")
                else dict(response)
            )

        except Exception as e:
            print(f"run_chat_inference ({provider}) error: {e}")
            return None

    # ---------------------------------------------------------------------------
    # WXO flow execution
    # ---------------------------------------------------------------------------

    def run_wxo_flow(
        self,
        flow_id: str,
        flow_input: Optional[Dict[str, Any]] = None,
        request_timeout: int = 60000,
        thread_id: Optional[str] = None,
        environment_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        agent_version: Optional[str] = None,
        execution_summary: Optional[bool] = None,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Run the latest "published" version of a WXO flow with a given flow ID.

        Uses POST /v1/orchestrate/flows/{flow_id}/run (relative to the versioned
        base_url, which already includes the "/orchestrate" segment for remote
        instances). Returns the flow output on success, None on failure.

        Parameters
        ----------
        flow_id:
            The flow ID to run (required).
        flow_input:
            The input defined by the flow model, sent as the JSON request body.
            Defaults to an empty object.
        request_timeout:
            The flow request timeout in milliseconds (query param, default 60000).
        thread_id:
            Optional ID of the thread where the flow was started
            (x-ibm-thread-id header).
        environment_id:
            Optional target environment ID - "draft" or "live"
            (x-ibm-environment-id header).
        agent_id:
            Optional caller agent ID (x-ibm-agent-id header).
        agent_version:
            Optional caller agent version (x-ibm-agent-version header).
        execution_summary:
            When True, generate the flow execution summary
            (x-ibm-flow-execution-summary header). Defaults to false server-side.

        Returns
        -------
        The flow output dict on success, None on failure or missing client.
        """
        wxo_client = self.client
        if not wxo_client:
            return None
        if not flow_id:
            print("run_wxo_flow: flow_id is required")
            return None
        try:
            url = f"{wxo_client['base_url']}/flows/{flow_id}/run"

            headers = dict(wxo_client["headers"])
            if thread_id is not None:
                headers["x-ibm-thread-id"] = thread_id
            if environment_id is not None:
                headers["x-ibm-environment-id"] = environment_id
            if agent_id is not None:
                headers["x-ibm-agent-id"] = agent_id
            if agent_version is not None:
                headers["x-ibm-agent-version"] = agent_version
            if execution_summary is not None:
                headers["x-ibm-flow-execution-summary"] = str(execution_summary).lower()

            params = {"request_timeout": request_timeout}

            response = requests.post(
                url,
                headers=headers,
                params=params,
                json=flow_input or {},
                verify=certifi.where(),
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"run_wxo_flow error: {e}")
            return None

    # ---------------------------------------------------------------------------
    # Iterative inference loop
    # ---------------------------------------------------------------------------

    def run_iterative_inference(
        self,
        messages: List[Dict[str, str]],
        number_of_iterations: int,
        provider: Optional[str] = None,
        model_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        continuation_message: str = "Generate Next Output.",
        on_iteration_complete: Optional[Callable[[int, Dict, List], None]] = None,
        progress_bar: Optional[bool] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """
        Run the iterative inference loop (provider-agnostic).

        After each assistant turn the continuation_message is appended as a user
        message so the model produces the next iteration.

        Parameters
        ----------
        messages:
            Initial rendered message list (system + user context).
        number_of_iterations:
            How many assistant turns to generate.
        provider:
            Override the instance provider. One of "watsonx", "openai", "rhai",
            "wxo", "ica".
        model_id:
            Required for openai / rhai / ica; optional for wxo when agent_id is
            set. Defaults to the instance model_id.
        params:
            Extra generation params forwarded per call. Defaults to the instance
            params.
        agent_id:
            WXO agent ID (wxo provider only). Defaults to the instance agent_id.
        continuation_message:
            User message injected between iterations.
        on_iteration_complete:
            Optional callback(iteration_index, result, current_messages) called after
            each successful assistant turn - use this to persist results to a database.
        progress_bar:
            Show a marimo progress bar over the iterations. Defaults to the
            instance ``self.progress_bar`` setting. Silently ignored when marimo
            is unavailable.

        Returns
        -------
        List of raw response dicts, one per completed iteration.
        """
        all_results: List[Dict[str, Any]] = []
        current_messages = list(messages)

        if self.client is None or not messages or not number_of_iterations:
            return all_results

        # Context-manager bar with manual update() so early termination
        # (break on failure) leaves a consistent progress display.
        bar = self._progress_bar_cm(
            progress_bar,
            total=number_of_iterations,
            title="Iterative inference",
        )

        with bar as _update:
            for i in range(number_of_iterations):
                result = self.run_chat_inference(
                    messages=current_messages,
                    provider=provider,
                    model_id=model_id,
                    params=params,
                    agent_id=agent_id,
                    **kwargs,
                )

                if result is None:
                    break

                all_results.append(result)

                choices = result.get("choices", [])
                if not choices:
                    _update()
                    break

                assistant_message = choices[0].get("message", {})
                current_messages.append(assistant_message)

                if on_iteration_complete:
                    try:
                        on_iteration_complete(i, result, current_messages)
                    except Exception as e:
                        print(
                            f"on_iteration_complete callback error (iteration {i + 1}): {e}"
                        )

                if i < number_of_iterations - 1:
                    current_messages.append(
                        {"role": "user", "content": continuation_message}
                    )

                _update()

        return all_results

    # ---------------------------------------------------------------------------
    # Batch inference
    # ---------------------------------------------------------------------------

    def run_batch_inference(
        self,
        items: List[Any],
        message_builder: Optional[Callable[[Any], List[Dict[str, str]]]] = None,
        provider: Optional[str] = None,
        model_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        on_item_complete: Optional[Callable[[int, Any, Optional[Dict]], None]] = None,
        progress_bar: Optional[bool] = None,
        include_item: bool = False,
        async_mode: bool = False,
        max_workers: int = 8,
        **kwargs: Any,
    ) -> List[Any]:
        """
        Run the same single-turn inference over a list of objects.

        Each object in ``items`` is converted into a messages list (via
        ``message_builder``) and sent through ``run_chat_inference``. Results are
        returned in the same order as the input, one entry per item - even in
        async mode.

        Unlike ``run_iterative_inference`` (which is a single growing
        conversation), this runs each item as an independent, stateless call -
        useful for scoring / extracting / classifying a collection of documents.

        Parameters
        ----------
        items:
            List of input objects. Each may be anything ``message_builder`` knows
            how to turn into a messages list. If ``message_builder`` is omitted,
            each item must already be a messages list
            (``List[{"role", "content"}]``).
        message_builder:
            Optional callable mapping one item -> messages list. Defaults to the
            identity function (item is used directly as the messages list).
        provider:
            Override the instance provider. One of "watsonx", "openai", "rhai",
            "wxo", "ica".
        model_id:
            Required for openai / rhai / ica; used for wxo when no agent_id is
            given. Defaults to the instance model_id.
        params:
            Extra generation params forwarded per call. Defaults to the instance
            params.
        agent_id:
            WXO agent ID (wxo provider only). Defaults to the instance agent_id.
        on_item_complete:
            Optional callback(index, item, result) called after each item - use
            this to persist results to a database as they come in. ``result`` is
            None when that item failed. In async mode it fires as each call
            finishes (so not necessarily in input order) and may run on a worker
            thread, so keep it thread-safe.
        progress_bar:
            Show a marimo progress bar over the items. Defaults to the instance
            ``self.progress_bar`` setting. Silently ignored when marimo is
            unavailable.
        include_item:
            When True, each return entry is a dict
            ``{"index": int, "item": <original pre-message_builder item>,
            "result": <response dict or None>}`` instead of the bare result.
        async_mode:
            When True, dispatch the calls concurrently using a thread pool
            (the provider clients are blocking I/O, so threads give real
            parallelism). Order of execution is not preserved, but the returned
            list is still aligned positionally with ``items``.
        max_workers:
            Maximum number of concurrent worker threads when ``async_mode`` is
            True. Defaults to 8.

        Returns
        -------
        A list aligned positionally with ``items``. Each entry is the raw
        response dict (or None for items that failed) when ``include_item`` is
        False, or the ``{"index", "item", "result"}`` dict when it is True.
        """
        if self.client is None or not items:
            return []

        build = message_builder or (lambda item: item)

        def _wrap(index: int, item: Any, result: Optional[Dict[str, Any]]):
            if include_item:
                return {"index": index, "item": item, "result": result}
            return result

        def _run_one(index: int, item: Any) -> Optional[Dict[str, Any]]:
            """Build messages for one item and run inference. Returns None on failure."""
            try:
                messages = build(item)
            except Exception as e:
                print(f"run_batch_inference: message_builder error (item {index}): {e}")
                return None
            if not messages:
                return None
            return self.run_chat_inference(
                messages=messages,
                provider=provider,
                model_id=model_id,
                params=params,
                agent_id=agent_id,
                **kwargs,
            )

        results: List[Any] = [None] * len(items)

        if async_mode:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            with self._progress_bar_cm(
                progress_bar, total=len(items), title="Batch inference (async)"
            ) as _update:
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    future_to_index = {
                        pool.submit(_run_one, i, item): i
                        for i, item in enumerate(items)
                    }
                    for future in as_completed(future_to_index):
                        i = future_to_index[future]
                        try:
                            result = future.result()
                        except Exception as e:
                            print(f"run_batch_inference: worker error (item {i}): {e}")
                            result = None

                        results[i] = _wrap(i, items[i], result)

                        if on_item_complete:
                            try:
                                on_item_complete(i, items[i], result)
                            except Exception as e:
                                print(
                                    f"on_item_complete callback error (item {i}): {e}"
                                )

                        _update()
            return results

        # Sequential path.
        for i, item in self._progress_iter(
            enumerate(items),
            progress_bar,
            total=len(items),
            title="Batch inference",
        ):
            result = _run_one(i, item)
            results[i] = _wrap(i, item, result)

            if on_item_complete:
                try:
                    on_item_complete(i, item, result)
                except Exception as e:
                    print(f"on_item_complete callback error (item {i}): {e}")

        return results

    # ---------------------------------------------------------------------------
    # Token aggregation
    # ---------------------------------------------------------------------------

    @staticmethod
    def aggregate_token_counts(
        all_inference_results: List[Dict[str, Any]],
    ) -> Optional[Dict[str, int]]:
        """
        Sum prompt/completion/total token counts across all iteration results.

        Returns None if no usage data is present.
        """
        if not all_inference_results:
            return None

        total_prompt = total_completion = total = 0
        has_usage = False

        for result in all_inference_results:
            usage = result.get("usage") if result else None
            if usage:
                has_usage = True
                total_prompt += usage.get("prompt_tokens", 0)
                total_completion += usage.get("completion_tokens", 0)
                total += usage.get("total_tokens", 0)

        if not has_usage:
            return None

        return {
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total,
        }
