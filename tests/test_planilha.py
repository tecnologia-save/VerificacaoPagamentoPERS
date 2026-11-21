"""Leitura da planilha e organização do lote. Dados FICTÍCIOS."""
from __future__ import annotations

import pytest
from openpyxl import Workbook

from VerificacaoPagamento.planilha import (
    PlanilhaInvalida,
    ler_planilha,
    normalizar_cnpj,
    normalizar_texto,
    planejar_lote,
    status_z_permitido,
    tipo_tributo,
)

CABECALHO = [
    "Parceiro", "Procurador", "Responsável Técnico", "CNPJ", "Empresa", "CNAE Principal",
    "Tese", "Tipo", "Mês-Tri", "Ano", "Tributo", "Data do Protocolo", "PERDCOMP",
    "Retificadora", "Valor Requerido (R$)", "Valor da Tese (R$)", "Valor Compensado (R$)",
    "Selic Compensada (R$)", "Compensação de Ofício (R$)", "Selic Comp. Ofício (R$)", "Aviso",
    "Valor Restituído/Ressarcido (R$)", "Selic (R$)", "Indeferimento (R$)",
    "Saldo Perdcomp (R$)", "Status", "Situação da Verificação",
]


def _linha(procurador="SAVE", cnpj="11222333000181", empresa="EMPRESA FICTICIA LTDA",
           perdcomp="111111111111111111111111", situacao=None):
    valores = [None] * len(CABECALHO)
    valores[0] = "PARCEIRO X"
    valores[1] = procurador
    valores[3] = cnpj
    valores[4] = empresa
    valores[7] = "RESSARCIMENTO"
    valores[8] = 3
    valores[9] = 2023
    valores[10] = "PIS"
    valores[12] = perdcomp
    valores[24] = 100.5
    valores[25] = "Em análise"
    valores[26] = situacao
    return valores


def _salvar(tmp_path, linhas, cabecalho=CABECALHO, outras_abas=True):
    wb = Workbook()
    ws = wb.active
    ws.title = "pers com saldo "
    ws.append(cabecalho)
    for linha in linhas:
        ws.append(linha)
    if outras_abas:  # só a PRIMEIRA aba conta
        wb.create_sheet("irpj csll ").append(["Parceiro", "Procurador", "x", "CNPJ"])
    caminho = tmp_path / "entrada.xlsx"
    wb.save(caminho)
    return caminho


def test_le_a_primeira_aba_e_os_campos(tmp_path):
    dados = ler_planilha(_salvar(tmp_path, [_linha()]))
    assert dados.nome_aba == "pers com saldo "
    assert dados.tem_coluna_situacao
    linha = dados.linhas[0]
    assert (linha.numero_linha, linha.procurador, linha.cnpj) == (2, "SAVE", "11222333000181")
    assert (linha.mes_tri, linha.ano, linha.tributo) == ("3", "2023", "PIS")
    assert linha.perdcomp == "111111111111111111111111"
    assert linha.valores["AA"] is None


def test_pendente_e_situacao_vazia(tmp_path):
    dados = ler_planilha(_salvar(tmp_path, [
        _linha(perdcomp="1"), _linha(perdcomp="2", situacao="Concluído"),
        _linha(perdcomp="3", situacao=" concluido "),
    ]))
    assert [ln.perdcomp for ln in dados.pendentes] == ["1"]


def test_cabecalho_deslocado_para_antes_do_login(tmp_path):
    cabecalho = ["Procurador", *CABECALHO]  # tudo uma coluna para a direita
    with pytest.raises(PlanilhaInvalida, match="B1"):
        ler_planilha(_salvar(tmp_path, [], cabecalho=cabecalho))


def test_aceita_planilha_sem_a_coluna_de_saida(tmp_path):
    dados = ler_planilha(_salvar(tmp_path, [_linha()[:26]], cabecalho=CABECALHO[:26]))
    assert not dados.tem_coluna_situacao
    assert len(dados.pendentes) == 1


def test_linha_vazia_no_meio_nao_esconde_o_resto(tmp_path):
    vazia = [None] * len(CABECALHO)
    dados = ler_planilha(_salvar(tmp_path, [_linha(perdcomp="1"), vazia, _linha(perdcomp="2")]))
    assert [ln.numero_linha for ln in dados.linhas] == [2, 4]


@pytest.mark.parametrize(("valor", "esperado"), [
    ("10.740.842/0001-33", "10740842000133"),
    ("10740842000133", "10740842000133"),
    (623904000173, "00623904000173"),
    (6.23904000173e11, "00623904000173"),
    ("", ""),
    (None, ""),
    ("123456789012345", ""),  # 15 dígitos
])
def test_normalizar_cnpj(valor, esperado):
    assert normalizar_cnpj(valor) == esperado


def test_normalizar_texto():
    assert normalizar_texto("Situação da Verificação") == "situacao da verificacao"
    assert normalizar_texto(" YURI ") == "yuri"
    assert normalizar_texto("GESTÃO D&S") == "gestao d&s"
    assert normalizar_texto("D&S") != normalizar_texto("DSR")


def test_planejar_lote_um_grupo_por_certificado_na_ordem_da_planilha(tmp_path):
    dados = ler_planilha(_salvar(tmp_path, [
        _linha(procurador="SAVE", cnpj="11111111000111", perdcomp="1"),
        _linha(procurador="D&S", cnpj="22222222000122", perdcomp="2"),
        _linha(procurador="SAVE", cnpj="33333333000133", perdcomp="3"),
        _linha(procurador="SAVE", cnpj="11111111000111", perdcomp="4"),
    ]))
    certificado = {"SAVE": "Save Inteligência", "D&S": "D&S"}
    grupos = planejar_lote([(ln, certificado[ln.procurador]) for ln in dados.linhas])
    assert [g.certificado for g in grupos] == ["Save Inteligência", "D&S"]
    save = grupos[0]
    assert [e.cnpj for e in save.empresas] == ["11111111000111", "33333333000133"]
    assert [ln.perdcomp for ln in save.empresas[0].linhas] == ["1", "4"]
    assert save.total_linhas == 3


@pytest.mark.parametrize(("valor", "esperado"), [
    ("PIS", "PIS"), ("PIS ", "PIS"), ("PIS/PASEP", "PIS"), ("PIS / PASEP", "PIS"),
    ("PIS /PASEP", "PIS"), ("COFINS", "COFINS"), ("Cofins ", "COFINS"), ("COFINS/FASE", "COFINS"),
    ("PIS/COFINS", ""), ("2024", ""), ("IRPJ", ""), ("", ""), (None, ""),
])
def test_tipo_tributo(valor, esperado):
    assert tipo_tributo(valor) == esperado


def test_status_z_permitido():
    assert status_z_permitido("Análise concluída", ("Análise concluída",))
    assert status_z_permitido(" ANALISE CONCLUIDA ", ("Análise concluída",))
    assert not status_z_permitido("Em análise", ("Análise concluída",))
    assert status_z_permitido("qualquer", ())


@pytest.mark.parametrize("tributo, codigo, esperado", [
    ("PIS", "19", "PIS"),
    ("Cofins", "18", "COFINS"),
    ("PIS", "04", "PAGAMENTO INDEVIDO"),         # código 04 manda, seja qual for a coluna K
    ("PIS/COFINS", "04", "PAGAMENTO INDEVIDO"),
    ("", "04", "PAGAMENTO INDEVIDO"),
    ("INSS", "19", "PAGAMENTO INDEVIDO"),        # sem PIS nem COFINS (20/11/2026)
    ("IRPJ", "18", "PAGAMENTO INDEVIDO"),
    ("CSLL", "04", "PAGAMENTO INDEVIDO"),
    ("IPI", "19", "PAGAMENTO INDEVIDO"),
    ("PIS/COFINS", "19", ""),                    # os dois juntos: indefinido
    ("", "19", ""),                              # coluna K vazia: indefinido
])
def test_tipo_credito(tributo, codigo, esperado):
    from VerificacaoPagamento.planilha import tipo_credito
    perdcomp = "1" * 18 + codigo + "0" * 4
    assert tipo_credito(tributo, perdcomp, pagamento_indevido=True, pela_coluna_k=True) == esperado
    # pela coluna K desligado: só o código 04 vira Pagamento Indevido
    so_04 = esperado if codigo == "04" or esperado != "PAGAMENTO INDEVIDO" else ""
    assert tipo_credito(tributo, perdcomp, pagamento_indevido=True, pela_coluna_k=False) == so_04
    # desligado: só a coluna K
    assert tipo_credito(tributo, perdcomp, pagamento_indevido=False) == tipo_tributo(tributo)
