from reels.http_util import format_ssl_error, ssl_verify, uses_system_trust_store


def test_ssl_verify_uses_system_store_when_truststore_available():
    ctx = ssl_verify()
    assert ctx is True or hasattr(ctx, "check_hostname")
    # On this project truststore is a dependency; expect OS store.
    assert uses_system_trust_store() is True


def test_format_ssl_error_mentions_antivirus():
    msg = format_ssl_error(
        Exception("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate")
    )
    assert "CERTIFICATE_VERIFY_FAILED" in msg
    assert "antivirus" in msg.lower() or "Avast" in msg
