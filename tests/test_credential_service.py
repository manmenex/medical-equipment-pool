from app.services.credential_service import CredentialService


def test_encrypted_fallback_round_trip(tmp_path, monkeypatch):
    service = CredentialService(tmp_path)
    # Force the encrypted-file fallback path regardless of whether a real
    # OS keyring backend happens to be available in the test environment.
    service._use_keyring = False

    assert service.has_credentials("ECRI") is False
    service.save_credentials("ECRI", "nurse.admin", "S3cret!")
    creds = service.get_credentials("ECRI")
    assert creds == ("nurse.admin", "S3cret!")
    assert service.has_credentials("ECRI") is True

    service.delete_credentials("ECRI")
    assert service.has_credentials("ECRI") is False


def test_credentials_are_encrypted_at_rest(tmp_path):
    service = CredentialService(tmp_path)
    service._use_keyring = False
    service.save_credentials("ECRI", "nurse.admin", "S3cretPassword123")

    raw_bytes = (tmp_path / "credentials.enc").read_bytes()
    assert b"S3cretPassword123" not in raw_bytes
    assert b"nurse.admin" not in raw_bytes
