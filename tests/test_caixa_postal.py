"""Caixa Postal: quais mensagens abrir e o laço de abertura. Dados FICTÍCIOS."""
from __future__ import annotations

import pytest

from VerificacaoPagamento import caixa_postal as cp

CNPJ = "11222333000181"


def test_so_as_importantes_nao_lidas_da_resposta():
    resposta = {"mensagens": [
        {"isn": 1, "assunto": "Importante  nova", "relevante": True, "lida": False},
        {"isn": 2, "assunto": "Importante lida", "relevante": True, "lida": True},
        {"isn": 3, "assunto": "Comum", "relevante": False, "lida": False},
    ]}
    assert cp.importantes_nao_lidas(resposta) == [cp.MensagemDaLista("1", "Importante nova")]


def test_resposta_sem_os_campos_nao_adivinha():
    with pytest.raises(ValueError):
        cp.importantes_nao_lidas({"mensagens": [{"isn": 1, "assunto": "x"}]})
    with pytest.raises(ValueError):
        cp.importantes_nao_lidas({"outra": []})


def test_normal_compara_sem_acento_e_sem_caixa():
    assert cp.normal("  Não   Lida ") == "nao lida"


@pytest.fixture
def caixa(monkeypatch):
    """Caixa Postal falsa: `nao_lidas` some da lista quando é aberta;
    `sem_titulo`: abre (some da lista) sem o título aparecer;
    `nao_abre`: o clique não abre."""
    estado = {"nao_lidas": [], "sem_titulo": set(), "nao_abre": set(), "aberturas": []}

    def listar(page, cnpj):
        assert cnpj == CNPJ
        return list(estado["nao_lidas"])

    def abrir(page, cnpj, mensagem):
        estado["aberturas"].append(mensagem.isn)
        if mensagem.isn in estado["nao_abre"]:
            return False, ""
        estado["nao_lidas"] = [m for m in estado["nao_lidas"] if m.isn != mensagem.isn]
        if mensagem.isn in estado["sem_titulo"]:
            return False, ""
        return True, f"Titulo {mensagem.isn}"

    monkeypatch.setattr(cp, "listar", listar)
    monkeypatch.setattr(cp, "_listar_insistindo", lambda page, cnpj: listar(page, cnpj))
    monkeypatch.setattr(cp, "abrir", abrir)
    return estado


def test_abre_todas_e_anota_cada_uma_uma_vez(caixa):
    caixa["nao_lidas"] = [cp.MensagemDaLista("1", "Intimação"), cp.MensagemDaLista("2", "Aviso")]
    anotadas = []
    assert cp.abrir_todas(None, CNPJ, ao_abrir=lambda isn, a: anotadas.append((isn, a))) == 2
    assert anotadas == [("1", "Intimação"), ("2", "Aviso")]


def test_aberta_sem_o_titulo_na_tela_conta_quando_sai_da_lista(caixa):
    caixa["nao_lidas"] = [cp.MensagemDaLista("1", "Intimação")]
    caixa["sem_titulo"] = {"1"}
    anotadas = []
    assert cp.abrir_todas(None, CNPJ, ao_abrir=lambda isn, a: anotadas.append(isn)) == 1
    assert anotadas == ["1"]


def test_sem_nenhuma_importante_nao_abre_nada(caixa):
    assert cp.abrir_todas(None, CNPJ, ao_abrir=lambda isn, a: None) == 0
    assert caixa["aberturas"] == []


def test_mensagem_que_nao_abre_e_erro_e_nao_e_anotada(caixa):
    caixa["nao_lidas"] = [cp.MensagemDaLista("1", "Intimação"), cp.MensagemDaLista("2", "Aviso")]
    caixa["nao_abre"] = {"2"}
    anotadas = []
    with pytest.raises(cp.CaixaPostalNaoReconhecida, match="continuam nao lidas"):
        cp.abrir_todas(None, CNPJ, ao_abrir=lambda isn, a: anotadas.append(isn))
    assert anotadas == ["1"]
    assert caixa["aberturas"].count("2") == cp.MAX_RODADAS
