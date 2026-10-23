import pytest

from kestrel.connection.address_guard import is_allowed


def resolver_for(mapping):
    def resolve(host):
        if host not in mapping:
            raise OSError(f"no address for {host}")
        return mapping[host]
    return resolve


def must_not_resolve(host):
    raise AssertionError("local mode must not resolve names")


@pytest.mark.parametrize("url", ["http://localhost/x", "http://10.0.0.1/x", "http://169.254.169.254/latest",
                                 "http://internal.example/x"])
def test_local_mode_allows_everything_without_resolving(url):
    assert is_allowed(url, "local", must_not_resolve)


@pytest.mark.parametrize("url", [
    "http://localhost:8001/chat", "http://api.localhost/chat", "http://127.0.0.1/chat", "http://[::1]/chat",
    "http://10.1.2.3/chat", "http://172.16.0.1/chat", "http://192.168.1.1/chat",
    "http://169.254.169.254/latest/meta-data", "http://100.100.100.200/x", "http://0.0.0.0/x",
    "http://224.0.0.1/x", "http://[::ffff:127.0.0.1]/x", "http://[fd00:ec2::254]/x",
])
def test_hosted_mode_refuses_local_and_private_addresses(url):
    assert not is_allowed(url, "hosted", resolver_for({}))


def test_hosted_mode_refuses_a_name_that_resolves_to_a_private_address():
    assert not is_allowed("http://internal.example/chat", "hosted", resolver_for({"internal.example": ["10.0.0.5"]}))


def test_hosted_mode_refuses_when_any_resolved_address_is_private():
    resolve = resolver_for({"mixed.example": ["93.184.216.34", "10.0.0.5"]})
    assert not is_allowed("http://mixed.example/chat", "hosted", resolve)


def test_hosted_mode_allows_a_name_that_resolves_only_to_public_addresses():
    assert is_allowed("https://agent.example/chat", "hosted", resolver_for({"agent.example": ["93.184.216.34"]}))


def test_a_resolver_error_counts_as_allowed():
    assert is_allowed("http://unknown.example/chat", "hosted", resolver_for({}))
