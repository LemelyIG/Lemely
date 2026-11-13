"""Thin ``httpx`` client for the Paymob Egypt APIs (billing spec §3).

No business logic: it builds requests, authenticates them and turns transport
failures and error statuses into :class:`PaymobError`. Callers decide what a
result means.

Three auth styles exist across the API (research 01 §1.3), and each method uses
the one Paymob documents for it:

* ``Authorization: Token <secret key>``: create intention, refund, void.
* ``Authorization: Bearer <auth token>``: inquiry, subscription plans and
  subscriptions. The token comes from ``POST api/auth/tokens`` with the API key,
  lives one hour, and is cached here for 50 minutes. The cache lock is held while
  the mint request is in flight, so concurrent callers share one mint rather than
  each minting (a slow mint delays them by up to ``timeout_seconds``). The skill's
  embedded copy says ``Token`` for the subscription calls; the live docs say Bearer
  on every one (``developers.paymob.com/paymob-docs/subscription/`` pages
  ``create-subscription-plan``, ``subscription-actions/list-subscription-details``,
  ``cancel-subscription``, ``suspend-subscription``, ``resume-subscription`` and
  ``update-subscription``, checked 2026-11-13). The live docs win (skill audit M1).
* None: ``POST api/acceptance/payments/pay`` (the payment token in the body
  authorises it).

**Error contract.** ``status_code`` is ``None`` when no usable answer came back:
a timeout, any transport failure (connect, read, write, protocol), or a 2xx whose
body is empty or not a JSON object (a proxy or maintenance page). Then
``outcome_unknown`` is ``True``: the request may have been applied, so the
caller must inquire and must never read the failure as a decline. ``timeout`` is
the narrower flag for a deadline that expired. The exceptions are
``PaymobNotConfigured`` (nothing was sent) and a received non-2xx status, which
carries ``status_code``, with one exception: a 5xx on a write (create intention,
pay with token, refund, void, create plan, update, suspend, resume or cancel a
subscription) also sets ``outcome_unknown``, because a gateway error does not say
whether Paymob applied it. A read (inquiry, get subscription, last transaction)
keeps a 5xx as a known failure. A write whose auth-token mint fails is a known
failure too: nothing was sent (``outcome_unknown`` ``False``, ``status_code`` ``None``,
the mint error chained as ``__cause__``). An empty 2xx is
never turned into ``{}``: no Paymob endpoint documents one, and ``{}`` would read
as a definite failure.

**Never retried.** Paymob has no idempotency keys (research 02 §8), so a write
that is sent once is never sent again by this module. A
timeout is raised with ``timeout=True`` so the caller inquires before doing
anything else (spec §6). The single exception is an idempotent ``GET`` whose
cached auth token Paymob rejects with 401: the token is replaced and that one
``GET`` is repeated once. Every other 401 drops the cached token and is raised.

**Secrets stay out of errors.** Messages carry method, path and status only. The
parsed error body is kept on :attr:`PaymobError.body` for diagnosis, but any
string in it that contains a credential this client holds or was handed (secret
key, API key, auth token, card token, payment token) is replaced first, as is any
``Bearer ...`` / ``Token ...`` header-shaped text. Nothing here logs.
"""

from __future__ import annotations

import re
import threading
import time
from typing import TYPE_CHECKING, Any, Final, Literal

import httpx

from lemely.runtime.errors import ExternalServiceError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from lemely.runtime.config import PaymobSettings

#: Plan frequencies (days) Paymob accepts (research 02 §6).
SUBSCRIPTION_FREQUENCIES: Final[frozenset[int]] = frozenset({7, 15, 30, 60, 90, 180, 360})
#: The auth token lives an hour; renew well before.
AUTH_TOKEN_TTL_SECONDS: Final = 50 * 60

#: A decoded JSON object. ``httpx`` hands bodies back untyped; the one explicit ``Any``
#: lives here so the rest of the module (and its callers) read ``JsonObject``.
type JsonObject = dict[str, Any]  # type: ignore[explicit-any]

_REDACTED: Final = "[redacted]"
_HEADER_SHAPED: Final = re.compile(r"\b(?:Bearer|Token)\s+[A-Za-z0-9._~+/=-]{8,}")

_Auth = Literal["secret", "bearer", "none"]


class PaymobError(ExternalServiceError):
    """A Paymob call failed: transport error, timeout, bad body or error status.

    ``status_code is None`` means no usable answer came back, and then
    ``outcome_unknown`` is ``True`` (unless the call was never sent, see
    :class:`PaymobNotConfigured`): the caller must inquire before any retry and
    must not treat the failure as a decline. ``timeout`` is ``True`` only when a
    deadline expired. A received error status sets ``status_code`` and leaves
    ``outcome_unknown`` ``False``, except a 5xx on a write.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        timeout: bool = False,
        body: Mapping[str, object] | None = None,
        outcome_unknown: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.timeout = timeout
        self.body: JsonObject = dict(body or {})
        self.outcome_unknown = status_code is None if outcome_unknown is None else outcome_unknown


class PaymobNotConfigured(PaymobError):
    """A credential this call needs is not set (see ``PaymobSettings``).

    Raised before anything is sent, so the outcome is known: nothing happened.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, outcome_unknown=False)


def _scrub(value: object, secrets: tuple[str, ...]) -> object:
    """Copy ``value`` with every credential-bearing string replaced."""
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, _REDACTED)
        return _HEADER_SHAPED.sub(_REDACTED, value)
    if isinstance(value, dict):
        return {_scrub(k, secrets): _scrub(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, secrets) for v in value]
    return value


def _require_amount(amount_cents: int) -> int:
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int) or amount_cents <= 0:
        raise ValueError(
            f"amount_cents must be a positive integer number of piasters, got {amount_cents!r}"
        )
    return amount_cents


class PaymobClient:
    """One process-wide client; thread-safe for the auth-token cache."""

    def __init__(
        self,
        settings: PaymobSettings,
        *,
        http: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._http = http if http is not None else httpx.Client(timeout=settings.timeout_seconds)
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._lock = threading.Lock()

    # -- plumbing -------------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def _url(self, path: str) -> str:
        return f"{self._settings.api_base}/{path.lstrip('/')}"

    def _secret_header(self) -> dict[str, str]:
        if self._settings.secret_key is None:
            raise PaymobNotConfigured("Paymob secret key is not configured")
        return {"Authorization": f"Token {self._settings.secret_key.get_secret_value()}"}

    def _auth_token(self) -> str:
        """The cached auth token, minted from the API key when absent or stale."""
        with self._lock:
            now = self._clock()
            if self._token is not None and now < self._token_expires_at:
                return self._token
            self._token = None
            if self._settings.api_key is None:
                raise PaymobNotConfigured("Paymob API key is not configured")
            data = self._send(
                "POST",
                "api/auth/tokens",
                json={"api_key": self._settings.api_key.get_secret_value()},
            )
            token = data.get("token") if data is not None else None
            if not isinstance(token, str) or not token:
                raise PaymobError("Paymob auth response carried no token")
            self._token = token
            self._token_expires_at = now + AUTH_TOKEN_TTL_SECONDS
            return token

    def _forget_token(self, rejected: str) -> None:
        """Drop the cached token, unless another thread already replaced it."""
        with self._lock:
            if self._token == rejected:
                self._token = None

    def _secrets(self, *extra: str | None) -> tuple[str, ...]:
        held = (
            self._settings.secret_key.get_secret_value() if self._settings.secret_key else None,
            self._settings.api_key.get_secret_value() if self._settings.api_key else None,
            self._token,
            *extra,
        )
        return tuple(s for s in held if s)

    def _once(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object] | None,
    ) -> httpx.Response:
        """Send one request; a transport failure becomes a :class:`PaymobError`."""
        try:
            return self._http.request(
                method,
                self._url(path),
                headers=dict(headers),
                json=dict(json) if json is not None else None,
                timeout=self._settings.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise PaymobError(f"Paymob {method} {path} timed out", timeout=True) from exc
        except httpx.HTTPError as exc:
            raise PaymobError(f"Paymob {method} {path} failed: {type(exc).__name__}") from exc

    def _send(
        self,
        method: str,
        path: str,
        *,
        auth: _Auth = "none",
        json: Mapping[str, object] | None = None,
        allow_404: bool = False,
        sensitive: tuple[str | None, ...] = (),
        bearer: str | None = None,
        write: bool = False,
    ) -> JsonObject | None:
        """Send a request and return its JSON object, or ``None`` for an allowed 404.

        ``bearer`` is a token the caller already fetched (and put in the body);
        otherwise a ``bearer`` call fetches its own. A ``write`` is sent exactly
        once and a 5xx on it is an unknown outcome; only an idempotent ``GET``
        rejected with 401 is repeated, once, under a fresh token.
        """
        token: str | None = None
        tried: list[str] = []
        headers: dict[str, str] = {}
        if auth == "secret":
            headers = self._secret_header()
        elif auth == "bearer":
            if bearer is not None:
                token = bearer
            else:
                try:
                    token = self._auth_token()
                except PaymobNotConfigured:
                    raise
                except PaymobError as exc:
                    if not write:
                        raise
                    # The token is minted before the write is sent, so a mint that timed out,
                    # was refused or came back unreadable means the write never left: a known
                    # failure, not an unknown outcome (no status either, as the write got none).
                    raise PaymobError(
                        f"Paymob {method} {path} was not sent: no auth token", outcome_unknown=False
                    ) from exc
            headers = {"Authorization": f"Bearer {token}"}
            tried.append(token)
        response = self._once(method, path, headers=headers, json=json)
        if response.status_code == 401 and token is not None:
            self._forget_token(token)
            if method == "GET":
                token = self._auth_token()
                tried.append(token)
                response = self._once(
                    method, path, headers={"Authorization": f"Bearer {token}"}, json=json
                )
                if response.status_code == 401:
                    self._forget_token(token)
        if allow_404 and response.status_code == 404:
            return None
        parsed: object
        try:
            parsed = response.json() if response.content else None
        except ValueError:
            parsed = None
        if not 200 <= response.status_code < 300:
            scrubbed = _scrub(parsed, self._secrets(*tried, *sensitive))
            raise PaymobError(
                f"Paymob {method} {path} returned {response.status_code}",
                status_code=response.status_code,
                body=scrubbed if isinstance(scrubbed, dict) else None,
                # A gateway 5xx on a write says nothing about whether Paymob applied it,
                # so it is unknown even though the status is set.
                outcome_unknown=write and response.status_code >= 500,
            )
        if not isinstance(parsed, dict):
            # A 2xx we cannot read (empty, HTML, a JSON array): the call may well
            # have been applied, so this is "unknown", never a definite failure.
            raise PaymobError(
                f"Paymob {method} {path} returned {response.status_code} with no JSON object body",
                outcome_unknown=True,
            )
        return parsed

    def _request(
        self,
        method: str,
        path: str,
        *,
        auth: _Auth,
        json: Mapping[str, object] | None = None,
        sensitive: tuple[str | None, ...] = (),
        write: bool = False,
    ) -> JsonObject:
        result = self._send(method, path, auth=auth, json=json, sensitive=sensitive, write=write)
        if result is None:  # only possible with allow_404, never passed here
            raise PaymobError(f"Paymob {method} {path} returned 404", status_code=404)
        return result

    # -- intentions -----------------------------------------------------------

    def create_intention(self, body: Mapping[str, object]) -> JsonObject:
        """``POST v1/intention/`` (one-off, or with ``subscription_plan_id``)."""
        return self._request("POST", "v1/intention/", auth="secret", json=body, write=True)

    # -- inquiry --------------------------------------------------------------

    def inquire_by_order_ref(self, merchant_order_id: str) -> JsonObject | None:
        """Last transaction for our ``special_reference``; ``None`` when there is none."""
        token = self._auth_token()
        return self._send(
            "POST",
            "api/ecommerce/orders/transaction_inquiry",
            auth="bearer",
            bearer=token,
            json={"auth_token": token, "merchant_order_id": merchant_order_id},
            allow_404=True,
        )

    def inquire_by_transaction(self, transaction_id: int) -> JsonObject | None:
        """``GET api/acceptance/transactions/{id}``; ``None`` when unknown."""
        return self._send(
            "GET",
            f"api/acceptance/transactions/{int(transaction_id)}",
            auth="bearer",
            allow_404=True,
        )

    # -- refund / void --------------------------------------------------------

    def refund(self, *, transaction_id: int, amount_cents: int) -> JsonObject:
        """``POST api/acceptance/void_refund/refund``; ``amount_cents`` in piasters."""
        return self._request(
            "POST",
            "api/acceptance/void_refund/refund",
            auth="secret",
            json={
                "transaction_id": int(transaction_id),
                "amount_cents": _require_amount(amount_cents),
            },
            write=True,
        )

    def void(self, *, transaction_id: int) -> JsonObject:
        """``POST api/acceptance/void_refund/void``: cancel a card transaction.

        Card only, and only before settlement (the same business day); after that
        Paymob answers an error status and the caller must use :meth:`refund`.
        """
        return self._request(
            "POST",
            "api/acceptance/void_refund/void",
            auth="secret",
            json={"transaction_id": int(transaction_id)},
            write=True,
        )

    # -- subscriptions --------------------------------------------------------

    def create_plan(
        self,
        *,
        name: str,
        frequency_days: int,
        amount_cents: int,
        integration_id: int,
        webhook_url: str,
        retrial_days: int | None = None,
        reminder_days: int | None = None,
        use_transaction_amount: bool = False,
    ) -> JsonObject:
        """``POST api/acceptance/subscription-plans`` (``integration`` must be MOTO)."""
        if frequency_days not in SUBSCRIPTION_FREQUENCIES:
            raise ValueError(
                f"frequency {frequency_days} is not one of {sorted(SUBSCRIPTION_FREQUENCIES)}"
            )
        body = {
            "frequency": frequency_days,
            "name": name[:200],
            "integration": int(integration_id),
            "amount_cents": _require_amount(amount_cents),
            "webhook_url": webhook_url,
            "use_transaction_amount": use_transaction_amount,
            "plan_type": "rent",
            "is_active": True,
            "number_of_deductions": None,
            "reminder_days": reminder_days,
            "retrial_days": retrial_days,
        }
        return self._request(
            "POST", "api/acceptance/subscription-plans", auth="bearer", json=body, write=True
        )

    def get_subscription(self, subscription_id: int) -> JsonObject:
        return self._request(
            "GET", f"api/acceptance/subscriptions/{int(subscription_id)}", auth="bearer"
        )

    def update_subscription(
        self,
        subscription_id: int,
        *,
        amount_cents: int | None = None,
        ends_at: str | None = None,
        next_billing: str | None = None,
    ) -> JsonObject:
        body: JsonObject = {}
        if amount_cents is not None:
            body["amount_cents"] = _require_amount(amount_cents)
        if ends_at is not None:
            body["ends_at"] = ends_at
        if next_billing is not None:
            body["next_billing"] = next_billing
        if not body:
            raise ValueError("nothing to update on the subscription")
        return self._request(
            "PUT",
            f"api/acceptance/subscriptions/{int(subscription_id)}",
            auth="bearer",
            json=body,
            write=True,
        )

    def _subscription_action(self, subscription_id: int, action: str) -> JsonObject:
        return self._request(
            "POST",
            f"api/acceptance/subscriptions/{int(subscription_id)}/{action}",
            auth="bearer",
            write=True,
        )

    def suspend_subscription(self, subscription_id: int) -> JsonObject:
        return self._subscription_action(subscription_id, "suspend")

    def resume_subscription(self, subscription_id: int) -> JsonObject:
        return self._subscription_action(subscription_id, "resume")

    def cancel_subscription(self, subscription_id: int) -> JsonObject:
        return self._subscription_action(subscription_id, "cancel")

    def last_transaction(self, subscription_id: int) -> JsonObject:
        return self._request(
            "GET",
            f"api/acceptance/subscriptions/{int(subscription_id)}/last-transaction",
            auth="bearer",
        )

    # -- merchant-initiated (MOTO) --------------------------------------------

    def pay_with_token(self, *, card_token: str, payment_token: str) -> JsonObject:
        """``POST api/acceptance/payments/pay`` with a saved-card token (research 02 §5)."""
        return self._request(
            "POST",
            "api/acceptance/payments/pay",
            auth="none",
            json={
                "source": {"identifier": card_token, "subtype": "TOKEN"},
                "payment_token": payment_token,
            },
            sensitive=(card_token, payment_token),
            write=True,
        )


__all__ = [
    "AUTH_TOKEN_TTL_SECONDS",
    "SUBSCRIPTION_FREQUENCIES",
    "PaymobClient",
    "PaymobError",
    "PaymobNotConfigured",
]
