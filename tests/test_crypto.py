from utils.crypto import decrypt_secret, encrypt_secret, load_fernet_key


def test_round_trip(monkeypatch):
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    monkeypatch.setenv("SYNC_CREDENTIALS_KEY", key.decode())
    token = encrypt_secret('{"api_key":"x","api_secret":"y"}')
    assert token != '{"api_key":"x","api_secret":"y"}'
    assert decrypt_secret(token) == '{"api_key":"x","api_secret":"y"}'


def test_load_fernet_key_requires_env(monkeypatch):
    monkeypatch.delenv("SYNC_CREDENTIALS_KEY", raising=False)
    try:
        load_fernet_key()
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "SYNC_CREDENTIALS_KEY" in str(e)
