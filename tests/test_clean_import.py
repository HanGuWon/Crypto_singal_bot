from __future__ import annotations


def test_public_package_imports_without_runtime_data_directory() -> None:
    import crypto_signal_bot.cli
    import crypto_signal_bot.data.collector
    import crypto_signal_bot.data.models
    import crypto_signal_bot.data.quality
    import crypto_signal_bot.data.store

    assert crypto_signal_bot.cli is not None
    assert crypto_signal_bot.data.models is not None
