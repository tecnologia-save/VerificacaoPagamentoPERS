"""PortalReal.processar_linha sem navegador: a troca PIS <-> COFINS quando a
Receita recusa o tipo de crédito. Dados FICTÍCIOS."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from VerificacaoPagamento import portal as mod
from VerificacaoPagamento.config import (
    SITUACAO_PAGAMENTO_REALIZADO,
    SITUACAO_PERDCOMP_CANCELADO,
    SITUACAO_TIPO_CREDITO_DIVERGENTE,
)
from VerificacaoPagamento.desfechos import Desfecho, PerdcompCancelado, TipoCreditoDivergente
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


def test_perdcomp_cancelado_vai_para_a_aa_e_segue(cenario, monkeypatch):
    """Regra do usuário (19/11/2026): "O documento que contém o detalhamento do
    crédito encontra-se cancelado" -> AA "Perdcomp cancelado", próxima linha,
    sem tentar o outro tributo."""
    portal, sessao, eventos, recusados = cenario

    def concluir_cancelado(page, **kw):
        raise PerdcompCancelado("O documento que contém o detalhamento do crédito encontra-se cancelado")

    monkeypatch.setattr(mod, "concluir_declaracao", concluir_cancelado)
    desfecho = portal.processar_linha(sessao, _linha("PIS"))
    assert desfecho.ok
    assert desfecho.situacao == SITUACAO_PERDCOMP_CANCELADO == "Perdcomp cancelado"
    assert desfecho.tela_conhecida is False        # a próxima linha recarrega o módulo
    assert not desfecho.tributo_corrigido
    assert [e for e in eventos if e[0] == "preencher"] == [("preencher", "PIS")]


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


def test_pagamento_indevido_seleciona_o_tipo_e_recusado_vai_direto_para_a_aa(cenario, monkeypatch):
    """Regra de 20/11/2026: código 04 / coluna K sem PIS nem COFINS -> "Pagamento
    Indevido ou a Maior"; se a Receita recusar, não há troca a tentar."""
    from VerificacaoPagamento import planilha
    monkeypatch.setattr(planilha, "PAGAMENTO_INDEVIDO_ATIVO", True)
    portal, sessao, eventos, recusados = cenario
    linha = LinhaPerdcomp(numero_linha=7, cnpj=CNPJ, tributo="INSS",
                          perdcomp="1" * 18 + "04" + "0" * 4)
    desfecho = portal.processar_linha(sessao, linha)
    assert desfecho.situacao == SITUACAO_PAGAMENTO_REALIZADO
    assert not desfecho.tributo_corrigido
    assert [e for e in eventos if e[0] == "preencher"] == [("preencher", "PAGAMENTO INDEVIDO")]

    eventos.clear()
    recusados.add("PAGAMENTO INDEVIDO")
    desfecho = portal.processar_linha(sessao, linha)
    assert desfecho.situacao == SITUACAO_TIPO_CREDITO_DIVERGENTE
    assert desfecho.tela_conhecida is False
    assert [e for e in eventos if e[0] == "preencher"] == [("preencher", "PAGAMENTO INDEVIDO")]


def _cenario_nao_pertence(cenario, monkeypatch, nao_pertence: set[str]):
    from VerificacaoPagamento.desfechos import PerdcompNaoPertence

    portal, sessao, eventos, _ = cenario
    atual = {"t": ""}

    def preencher(page, *, tributo, perdcomp, diagnostico):
        atual["t"] = tributo
        eventos.append(("preencher", tributo))
        return perdcomp

    def concluir(page, **kw):
        if atual["t"] in nao_pertence:
            raise PerdcompNaoPertence("O PER/DCOMP informado não pertence ao contribuinte e nem a "
                                      "uma empresa sucedida")
        return Desfecho(True, "pago", situacao=SITUACAO_PAGAMENTO_REALIZADO)

    monkeypatch.setattr(mod, "preencher_identificacao", preencher)
    monkeypatch.setattr(mod, "concluir_declaracao", concluir)
    return portal, sessao, eventos


@pytest.mark.parametrize("k, codigo, esperado", [
    ("PIS", "19", ["PIS", "COFINS", "PAGAMENTO INDEVIDO"]),
    ("COFINS", "18", ["COFINS", "PIS", "PAGAMENTO INDEVIDO"]),
    ("INSS", "24", ["PAGAMENTO INDEVIDO", "PIS", "COFINS"]),
])
def test_nao_pertence_ao_contribuinte_troca_o_tipo_e_refaz_tudo(cenario, monkeypatch, k, codigo,
                                                                 esperado):
    """Regra do usuário (21/11/2026): "O PER/DCOMP informado não pertence ao
    contribuinte" -> PIS -> COFINS -> Pagamento Indevido (e vice-versa),
    preenchendo tudo de novo a cada troca."""
    portal, sessao, eventos = _cenario_nao_pertence(cenario, monkeypatch, set(esperado[:2]))
    linha = LinhaPerdcomp(numero_linha=7, cnpj=CNPJ, tributo=k, perdcomp="1" * 18 + codigo + "0" * 4)
    desfecho = portal.processar_linha(sessao, linha)
    assert desfecho.situacao == SITUACAO_PAGAMENTO_REALIZADO
    assert [e[1] for e in eventos if e[0] == "preencher"] == esperado
    assert eventos.count(("modulo",)) == 2                 # refez do zero a cada troca
    # a coluna K só é corrigida para PIS/COFINS
    assert desfecho.tributo_corrigido == (esperado[2] if esperado[2] in ("PIS", "COFINS") else "")


def test_nao_pertence_com_todos_os_tipos_vai_para_a_aa(cenario, monkeypatch):
    from VerificacaoPagamento.config import SITUACAO_PERDCOMP_NAO_PERTENCE

    portal, sessao, eventos = _cenario_nao_pertence(
        cenario, monkeypatch, {"PIS", "COFINS", "PAGAMENTO INDEVIDO"})
    desfecho = portal.processar_linha(sessao, _linha("COFINS"))
    assert desfecho.ok and desfecho.situacao == SITUACAO_PERDCOMP_NAO_PERTENCE
    assert desfecho.tela_conhecida is False
    assert [e[1] for e in eventos if e[0] == "preencher"] == ["COFINS", "PIS", "PAGAMENTO INDEVIDO"]
