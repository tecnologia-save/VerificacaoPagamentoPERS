"""Fixtures compartilhadas."""
from datetime import datetime

import pytest


@pytest.fixture(autouse=True)
def _relogio_de_dia(monkeypatch):
    """Os testes não dependem da hora em que rodam: fora da janela do
    Receitanet (1h–3h), senão a execução pausaria esperando as 3h01. O teste
    da janela troca o relógio por conta própria."""
    from VerificacaoPagamento import execucao

    monkeypatch.setattr(execucao, "_agora", lambda: datetime(2026, 11, 19, 10, 0))


@pytest.fixture(scope="session")
def navegador():
    """Um Chrome headless de verdade (o instalado na máquina). Pula se não abrir."""
    from patchright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, channel="chrome")
        except Exception as e:  # noqa: BLE001 — sem Chrome, o teste é pulado
            pytest.skip(f"Chrome indisponível: {type(e).__name__}")
        yield browser
        browser.close()
