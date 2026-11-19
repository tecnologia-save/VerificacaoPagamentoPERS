"""Bloqueio da Caixa Postal: o iframe do e-CAC abre a Caixa Postal no lugar do
PER/DCOMP (AGROFEG, 18/11/2026). Página FICTÍCIA, sem rede."""
from __future__ import annotations

from VerificacaoPagamento.navegacao import caixa_postal_no_lugar_do_modulo


def _pagina(navegador, src):
    page = navegador.new_page()
    page.set_content(f'<html><body><iframe id="frmApp" src="{src}" title="eCAC"></iframe></body></html>')
    return page


def test_caixa_postal_no_iframe_e_reconhecida(navegador):
    page = _pagina(navegador, "about:blank#https://www3.cav.receita.fazenda.gov.br/caixapostal/")
    try:
        assert caixa_postal_no_lugar_do_modulo(page)
    finally:
        page.close()


def test_perdcomp_no_iframe_nao_e_bloqueio(navegador):
    page = _pagina(navegador, "about:blank#https://www3.cav.receita.fazenda.gov.br/perdcomp-web/")
    try:
        assert not caixa_postal_no_lugar_do_modulo(page)
    finally:
        page.close()
