"""Salva o HTML (de cada frame) + screenshot da tela ATUAL do Chrome da automação.

Para levantar os seletores das próximas telas da Declaração de Compensação.
Conecta pelo --remote-debugging-port=9222 que o `ecac_login` abre e não
navega nem fecha a sessão.

Uso:
    1. Rode `python run.py` e, com o Chrome da automação aberto, pause pela
       janela de progresso (ou navegue manualmente) até a tela desejada.
    2. Em OUTRO terminal:  python debug_capturar_tela.py "rotulo_da_tela"
    3. Arquivos em debug_telas/<rotulo>_<data>_*.html e .png
"""
import sys
from pathlib import Path

from patchright.sync_api import sync_playwright

from VerificacaoPagamento.config import CDP_URL
from VerificacaoPagamento.diagnostico import capturar_tela

SAIDA_DIR = Path(__file__).parent / "debug_telas"


def capturar(rotulo: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()
        print(f"URL atual: {page.url}")
        capturar_tela(page, rotulo, SAIDA_DIR)
        browser.close()  # fecha só a conexão CDP, não o Chrome


if __name__ == "__main__":
    capturar(sys.argv[1] if len(sys.argv) > 1 else "tela")
