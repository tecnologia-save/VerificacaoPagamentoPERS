"""Aviso "este PER/DCOMP não é o original — recuperar o original?" -> "Sim"
(regra do usuário, 19/11/2026). Páginas FICTÍCIAS, sem rede."""
from __future__ import annotations

from VerificacaoPagamento.etapas_dcomp import responder_recuperar_original

AVISO_ORIGINAL = """
<div class="modal" role="dialog"><p>O PER/DCOMP informado não é o original. Deseja recuperar o
documento original?</p><button id="sim" onclick="document.body.dataset.sim='1'">Sim</button>
<button id="nao" onclick="document.body.dataset.nao='1'">Não</button></div>"""

AVISO_PENDENCIAS = """
<div class="modal" role="dialog"><p>O documento examinado apresenta pendências que não impedem
seu envio à RFB. Deseja verificá-las?</p>
<button onclick="document.body.dataset.sim='1'">Sim</button>
<button onclick="document.body.dataset.nao='1'">Não</button></div>"""


def _pagina(navegador, html):
    page = navegador.new_page()
    page.set_content(f"<html><body><h1>Crédito Original na Data de Entrega</h1>{html}</body></html>")
    return page


def test_aviso_de_original_clica_sim(navegador):
    page = _pagina(navegador, AVISO_ORIGINAL)
    try:
        assert responder_recuperar_original(page)
        assert page.evaluate("document.body.dataset.sim") == "1"
        assert page.evaluate("document.body.dataset.nao") is None
    finally:
        page.close()


def test_outro_popup_com_sim_nao_e_clicado(navegador):
    """O 'Sim' das pendências (que deve ser 'Não') e um título com 'Original'
    fora do popup não confundem a regra."""
    page = _pagina(navegador, AVISO_PENDENCIAS)
    try:
        assert not responder_recuperar_original(page)
        assert page.evaluate("document.body.dataset.sim") is None
    finally:
        page.close()
