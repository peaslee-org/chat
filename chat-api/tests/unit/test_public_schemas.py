from pydantic import BaseModel

FORBIDDEN = {
    "user_id", "user_sub", "input_prefix", "mesh_s3_key", "preview_s3_key",
    "audio_s3_key", "input_price_per_1k_tokens", "output_price_per_1k_tokens",
    "error_message",
}


def test_public_schemas_never_expose_private_fields():
    import app.schemas.public as public

    checked = 0
    for name in dir(public):
        cls = getattr(public, name)
        if isinstance(cls, type) and issubclass(cls, BaseModel) and cls.__module__ == public.__name__:
            leaked = FORBIDDEN & set(cls.model_fields)
            assert not leaked, f"{name} exposes {leaked}"
            checked += 1
    assert checked >= 9


def test_showcase_shape():
    from app.schemas.public import ShowcaseResponse

    s = ShowcaseResponse()
    assert (s.scans, s.transcriptions, s.conversations) == ([], [], [])
