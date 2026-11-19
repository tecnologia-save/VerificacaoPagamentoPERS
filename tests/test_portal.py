"""PortalReal.processar_linha sem navegador: a troca PIS <-> COFINS quando a
Receita recusa o tipo de crédito. Dados FICTÍCIOS."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from VerificacaoPagamento import portal as mod
from VerificacaoPagamento.config import (
    SITUACAO_PAGAMENTO_REALIZADO,
    SITUACAO_TIPO_CREDITO_DIVERGENTE,
)
from VerificacaoPagamento.desfechos import Desfecho, TipoCreditoDivergente
from VerificacaoPagamento.planilha import LinhaPerdcomp

CNPJ = "11111111000111"


@pytest.fixture
def cenario(monkeypatch, tmp_path):
    """`recusados`: tributos que a Receita recusa. Devolve (portal, sessao, eventos)."""
    eventos: list[tuple] = []
    recusados: set[str] = set()
    tributo_atual = {"t": ""}

    monkeypatch.setattr(mod._sessao, "cnpj_do_perfil_ativo", lambda page, timeout=0: CNPJ)
    monkeypatch.setattr(mod, "navegar_modulo_perdcomp", lambda page: eventos.append(("modulo",)))
    monkeypatch.setattr(mod, "conferencias_identificacao", lambda page, **kw: ())

    def preencher(page, *, tributo, perdcomp, diagnostico):
        tributo_atual["t"] = tributo
        eventos.append(("preencher", tributo))

    def concluir(page, **kw):
        if tributo_atual["t"] in recusados:
            raise TipoCreditoDivergente("Tipo do crédito informado neste documento diferente")
        return Desfecho(True, "pago", situacao=SITUACAO_PAGAMENTO_REALIZADO)

    monkeypatch.setattr(mod, "preencher_identificacao", preencher)
    monkeypatch.setattr(mod, "concluir_declaracao", concluir)
    portal = mod.PortalReal(project_dir=tmp_path, perfil_dir=None, pasta_debug=tmp_path / "dbg",
                            checkpoint=None, cancelado=lambda: False)
    monkeypatch.setattr(portal, "capturar", lambda sessao, rotulo: eventos.append(("captura", rotulo)))
    sessao = SimpleNamespace(page=object(), encerrada=False)
    return portal, sessao, eventos, recusados


def _linha(tributo="PIS"):
    return LinhaPerdcomp(numero_linha=7, cnpj=CNPJ, tributo=tributo, perdcomp="1" * 18 + "19" + "0" * 4)


def test_tributo_trocado_e_corrigido(cenario):
    portal, sessao, eventos, recusados = cenario
    recusados.add("PIS")
    desfecho = portal.processar_linha(sessao, _linha("PIS"))
    assert desfecho.situacao == SITUACAO_PAGAMENTO_REALIZADO
    assert desfecho.tributo_corrigido == "COFINS"
    assert [e for e in eventos if e[0] == "preencher"] == [("preencher", "PIS"), ("preencher", "COFINS")]


def test_recusado_com_pis_e_cofins_vai_para_a_aa_sem_fechar_o_navegador(cenario):
    """Regra do usuário (18/11/2026): a mesma mensagem com os dois tributos ->
    AA "Tipo do crédito informado neste documento diferente do tipo de crédito
    do PER/DCOMP" e segue para a próxima linha, no mesmo navegador."""
    portal, sessao, eventos, recusados = cenario
    recusados.update({"PIS", "COFINS"})
    desfecho = portal.processar_linha(sessao, _linha("PIS"))
    assert desfecho.ok
    assert desfecho.situacao == SITUACAO_TIPO_CREDITO_DIVERGENTE
    assert desfecho.situacao == ("Tipo do crédito informado neste documento diferente do tipo de "
                                 "crédito do PER/DCOMP")
    assert not desfecho.tributo_corrigido          # a coluna K não muda
    assert desfecho.tela_conhecida is False        # a próxima linha recarrega o módulo
    assert [e for e in eventos if e[0] == "preencher"] == [("preencher", "PIS"), ("preencher", "COFINS")]


def test_aviso_de_mensagens_importantes_que_trava_a_linha_bloqueia_a_empresa(cenario, monkeypatch):
    """AGROFEG (19/11/2026): o aviso "mensagens importantes ainda não lidas"
    aparece por cima do formulário e a Data de Vencimento não aceita a data."""
    from VerificacaoPagamento.desfechos import EmpresaBloqueadaNaCaixaPostal

    portal, sessao, eventos, recusados = cenario
    aviso = {"na_tela": False}
    monkeypatch.setattr(mod._sessao, "tem_mensagens_importantes",
                        lambda page, espera_ms=0: aviso["na_tela"])

    def concluir_travado(page, **kw):
        aviso["na_tela"] = True
        raise RuntimeError("CampoNaoConfirmado: Data de Vencimento")

    monkeypatch.setattr(mod, "concluir_declaracao", concluir_travado)
    with pytest.raises(EmpresaBloqueadaNaCaixaPostal):
        portal.processar_linha(sessao, _linha("PIS"))
    # e, com o aviso já na tela, a linha seguinte nem começa
    with pytest.raises(EmpresaBloqueadaNaCaixaPostal):
        portal.processar_linha(sessao, _linha("PIS"))


def test_erro_comum_sem_aviso_continua_erro_comum(cenario, monkeypatch):
    portal, sessao, eventos, recusados = cenario
    monkeypatch.setattr(mod._sessao, "tem_mensagens_importantes", lambda page, espera_ms=0: False)

    def concluir_com_erro(page, **kw):
        raise RuntimeError("tela inesperada")

    monkeypatch.setattr(mod, "concluir_declaracao", concluir_com_erro)
    with pytest.raises(RuntimeError, match="tela inesperada"):
        portal.processar_linha(sessao, _linha("PIS"))
