"""Native certificate validation scoped to the ChatGPT-plan HTTPS clients."""

from __future__ import annotations

import ssl
import urllib.request

from .provider import _NoRedirect


def native_opener() -> urllib.request.OpenerDirector:
    try:
        import truststore
    except ImportError:
        raise ValueError("install the chatgpt optional dependency") from None
    # A per-client context, without changing ssl globally. The native verifier
    # checks the chain and hostname; no invalid-certificate fallback is used.
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect(),
                                       urllib.request.HTTPSHandler(context=context))
