"""Diário + coluna AA. Dados FICTÍCIOS."""
from __future__ import annotations

import pytest
from openpyxl import Workbook, load_workbook

from tests.test_planilha import CABECALHO, _linha
from VerificacaoPagamento import registro as reg
from VerificacaoPagamento.config import SITUACAO_PAGAMENTO_REALIZADO, SITUACAO_VERIFICAR
from VerificacaoPagamento.planilha import ler_planilha

P1, P2, P3 = "1" * 24, "2" * 24, "3" * 24


@pytest.fixture
def planilha(tmp_path):
    wb = Workbook()
    aba = wb.active
    aba.title = "pis cofins "
    aba.append(CABECALHO[:26])  # sem a coluna AA: a gravação cria o cabeçalho
    for p in (P1, P2, P3):
        aba.append(_linha(perdcomp=p)[:26])
    wb.create_sheet("outra").append(["intocada"])
    caminho = tmp_path / "entrada.xlsx"
    wb.save(caminho)
    return caminho


@pytest.fixture
def registro(tmp_path, planilha):
    return reg.RegistroResultados(planilha, tmp_path / "resultados", tmp_path / "backups",
                                  salvar_a_cada=1)


def _aa(caminho):
    aba = load_workbook(caminho).worksheets[0]
    return [aba[f"AA{n}"].value for n in range(1, 5)]


def test_registrar_grava_a_aa_com_copia_de_seguranca(registro, planilha, tmp_path):
    dados = ler_planilha(planilha)
    registro.registrar(dados.linhas[1], SITUACAO_PAGAMENTO_REALIZADO, "ok")
    assert _aa(planilha) == ["Situação da Verificação", None, SITUACAO_PAGAMENTO_REALIZADO, None]
    assert load_workbook(planilha)["outra"]["A1"].value == "intocada"
    assert len(list((tmp_path / "backups").glob("*.xlsx"))) == 1
    assert registro.ler_diario() == {(3, P2): SITUACAO_PAGAMENTO_REALIZADO}


def test_envio_sem_desfecho_no_diario_vira_quarentena_na_proxima_execucao(registro, planilha):
    dados = ler_planilha(planilha)
    registro.marcar_envio(dados.linhas[0])                        # robô caiu aqui
    registro.marcar_envio(dados.linhas[2])
    registro.registrar(dados.linhas[2], SITUACAO_PAGAMENTO_REALIZADO)
    assert registro.ler_diario() == {(2, P1): SITUACAO_VERIFICAR, (4, P3): SITUACAO_PAGAMENTO_REALIZADO}


def test_reconciliar_tira_do_lote_o_que_o_diario_ja_tem(tmp_path, planilha):
    anterior = reg.RegistroResultados(planilha, tmp_path / "resultados", tmp_path / "backups",
                                      salvar_a_cada=99)
    dados = ler_planilha(planilha)
    anterior.marcar_envio(dados.linhas[0])  # e a AA nunca foi gravada

    novo = reg.RegistroResultados(planilha, tmp_path / "resultados", tmp_path / "backups")
    dados = ler_planilha(planilha)
    assert novo.reconciliar(dados) == 1
    assert [ln.perdcomp for ln in dados.pendentes] == [P2, P3]
    assert novo.salvar()
    assert _aa(planilha)[1] == SITUACAO_VERIFICAR


def test_linha_que_mudou_de_perdcomp_nao_recebe_o_resultado(registro, planilha):
    dados = ler_planilha(planilha)
    wb = load_workbook(planilha)
    wb.worksheets[0]["M2"] = "9" * 24  # alguém mexeu na planilha no meio da execução
    wb.save(planilha)
    registro.registrar(dados.linhas[0], SITUACAO_PAGAMENTO_REALIZADO)
    assert _aa(planilha)[1] is None
    assert registro.ler_diario() == {(2, P1): SITUACAO_PAGAMENTO_REALIZADO}  # continua no diário


def test_planilha_aberta_no_excel_nao_perde_nada(registro, planilha, monkeypatch):
    dados = ler_planilha(planilha)

    def recusa(*_args):
        raise PermissionError("arquivo em uso")

    monkeypatch.setattr(reg.os, "replace", recusa)
    registro.registrar(dados.linhas[0], SITUACAO_PAGAMENTO_REALIZADO)
    assert registro.pendentes_de_gravacao == 1 and "PermissionError" in registro.ultima_falha
    assert not list(planilha.parent.glob("~gravando_*"))  # temporário removido
    monkeypatch.undo()
    assert registro.salvar()
    assert _aa(planilha)[1] == SITUACAO_PAGAMENTO_REALIZADO


def test_em_segundo_plano_nao_segura_quem_registra(tmp_path, planilha):
    """O registrar volta na hora (o diário é síncrono); a coluna AA é gravada
    pela thread, e o fechar() garante tudo gravado no fim."""
    import time as _time

    registro = reg.RegistroResultados(planilha, tmp_path / "resultados", tmp_path / "backups",
                                      em_segundo_plano=True)
    dados = ler_planilha(planilha)
    inicio = _time.monotonic()
    registro.registrar(dados.linhas[0], SITUACAO_PAGAMENTO_REALIZADO)
    registro.registrar(dados.linhas[1], SITUACAO_VERIFICAR)
    assert _time.monotonic() - inicio < 1.0
    assert registro.ler_diario() == {(2, P1): SITUACAO_PAGAMENTO_REALIZADO, (3, P2): SITUACAO_VERIFICAR}
    assert registro.fechar()
    assert _aa(planilha)[1:3] == [SITUACAO_PAGAMENTO_REALIZADO, SITUACAO_VERIFICAR]


def test_envio_recusado_pelo_servidor_anula_o_enviando(registro, planilha):
    dados = ler_planilha(planilha)
    registro.marcar_envio(dados.linhas[0])
    registro.marcar_nao_transmitido(dados.linhas[0], "o e-CAC recusou o envio")
    assert registro.ler_diario() == {}          # volta para a fila, sem quarentena
    registro.marcar_envio(dados.linhas[0])      # nova tentativa que caiu no meio
    assert registro.ler_diario() == {(2, P1): SITUACAO_VERIFICAR}


def test_corrigir_tributo_grava_a_coluna_k_junto(registro, planilha):
    dados = ler_planilha(planilha)
    registro.corrigir_tributo(dados.linhas[0], "COFINS")
    registro.registrar(dados.linhas[0], SITUACAO_PAGAMENTO_REALIZADO)
    aba = load_workbook(planilha).worksheets[0]
    assert (aba["K2"].value, aba["AA2"].value) == ("COFINS", SITUACAO_PAGAMENTO_REALIZADO)
    assert registro.ler_diario() == {(2, P1): SITUACAO_PAGAMENTO_REALIZADO}


def test_perdcomp_ja_resolvido_em_outra_planilha_ou_linha_nao_volta(tmp_path, planilha):
    """Planilha dividida em partes (18/11/2026): as linhas mudam de número e o
    mesmo PER/DCOMP aparece repetido. O resultado vale pelo NÚMERO DO PER/DCOMP."""
    pasta = tmp_path / "resultados"
    outra = reg.RegistroResultados(tmp_path / "planilha_antiga.xlsx", pasta, tmp_path / "backups")
    dados = ler_planilha(planilha)
    from VerificacaoPagamento.planilha import LinhaPerdcomp
    outra.registrar(LinhaPerdcomp(numero_linha=499, perdcomp=P1, cnpj="1"), SITUACAO_PAGAMENTO_REALIZADO)
    dados.linhas[1].situacao_verificacao = "Pagamento não realizado, protocolação feita"
    dados.linhas[2].perdcomp = P2          # linha 4 repete o PER/DCOMP da linha 3

    registro = reg.RegistroResultados(planilha, pasta, tmp_path / "backups")
    assert registro.reconciliar(dados) == 2
    assert dados.linhas[0].situacao_verificacao == SITUACAO_PAGAMENTO_REALIZADO   # de outra planilha
    assert dados.linhas[2].situacao_verificacao == "Pagamento não realizado, protocolação feita"


# ── Coluna AB: número da Declaração protocolada (pedido do usuário, 18/11/2026) ─

NUM_1 = "34450.37448.181126.1.3.19-4627"
NUM_2 = "13548.70423.181126.1.3.19-7439"


def _ab(caminho):
    aba = load_workbook(caminho).worksheets[0]
    return [aba[f"AB{n}"].value for n in range(1, 5)]


def test_protocolada_grava_o_numero_na_ab(registro, planilha):
    from VerificacaoPagamento.config import SITUACAO_PROTOCOLADA
    dados = ler_planilha(planilha)
    registro.registrar(dados.linhas[0], SITUACAO_PROTOCOLADA, f"Declaração enviada — nº {NUM_1}")
    registro.registrar(dados.linhas[1], SITUACAO_PAGAMENTO_REALIZADO, "recusou")
    assert _aa(planilha)[1:3] == [SITUACAO_PROTOCOLADA, SITUACAO_PAGAMENTO_REALIZADO]
    assert _ab(planilha) == ["DCOMP protocolada", NUM_1, None, None]
    assert dados.linhas[0].numero_documento == NUM_1


def test_reconciliar_preenche_a_ab_dos_envios_antigos_pelo_perdcomp(tmp_path, planilha):
    """Os envios feitos antes da coluna AB existir: o número está no diário
    (de qualquer planilha) e vai para a AB, inclusive em PER/DCOMP repetido."""
    from VerificacaoPagamento.config import SITUACAO_PROTOCOLADA
    from VerificacaoPagamento.planilha import LinhaPerdcomp
    pasta = tmp_path / "resultados"
    antiga = reg.RegistroResultados(tmp_path / "planilha_antiga.xlsx", pasta, tmp_path / "backups")
    antiga.registrar(LinhaPerdcomp(numero_linha=499, perdcomp=P1, cnpj="1"), SITUACAO_PROTOCOLADA,
                     f"Declaração enviada — nº {NUM_1}")

    dados = ler_planilha(planilha)
    dados.linhas[0].situacao_verificacao = SITUACAO_PROTOCOLADA      # AA já gravada, AB vazia
    dados.linhas[1].situacao_verificacao = SITUACAO_PROTOCOLADA      # já tem AB: não mexe
    dados.linhas[1].numero_documento = NUM_2
    dados.linhas[2].perdcomp = P2                                    # repete a linha 3
    registro = reg.RegistroResultados(planilha, pasta, tmp_path / "backups")
    registro.reconciliar(dados)
    assert dados.linhas[0].numero_documento == NUM_1
    assert dados.linhas[1].numero_documento == NUM_2
    assert dados.linhas[2].situacao_verificacao == SITUACAO_PROTOCOLADA
    assert dados.linhas[2].numero_documento == NUM_2
    assert registro.salvar()
    # linha 4: o PER/DCOMP foi trocado só em memória — a trava "PER/DCOMP da
    # planilha mudou" não deixa gravar no lugar errado.
    assert _ab(planilha) == ["DCOMP protocolada", NUM_1, None, None]


# ── Duas sessões ao mesmo tempo (18/11/2026) ─────────────────────────────────

def test_sessao_2_tem_diario_proprio(tmp_path, planilha):
    s1 = reg.RegistroResultados(planilha, tmp_path / "resultados", tmp_path / "backups")
    s2 = reg.RegistroResultados(planilha, tmp_path / "resultados", tmp_path / "backups", sessao=2)
    assert s1.diario.name == "entrada_verificacao.csv"
    assert s2.diario.name == "entrada_sessao2_verificacao.csv"


def test_envio_em_andamento_da_outra_sessao_nao_vira_quarentena(tmp_path, planilha):
    """A sessão 1 reconcilia enquanto a 2 espera o desfecho de um envio: esse
    "enviando" recente NÃO é quarentena. Um antigo (robô caído) continua sendo."""
    pasta = tmp_path / "resultados"
    dados = ler_planilha(planilha)
    s2 = reg.RegistroResultados(planilha, pasta, tmp_path / "backups", sessao=2)
    s2.marcar_envio(dados.linhas[0])                       # agora: em andamento
    with open(s2.diario, "a", encoding="utf-8-sig", newline="") as f:
        f.write(f"01/01/2026 10:00:00;3;{P2};1;{reg.MARCA_ENVIANDO};\n")   # antigo: caiu
    s1 = reg.RegistroResultados(planilha, pasta, tmp_path / "backups")
    assert s1.reconciliar(dados) == 1
    assert dados.linhas[0].situacao_verificacao == ""
    assert dados.linhas[1].situacao_verificacao == SITUACAO_VERIFICAR
    # e a própria sessão 2 trata o SEU "enviando" sem desfecho como quarentena
    assert s2.ler_diario()[(2, P1)] == SITUACAO_VERIFICAR


def test_duas_sessoes_gravando_ao_mesmo_tempo_nao_perdem_resultado(tmp_path, planilha):
    import threading

    from VerificacaoPagamento.config import SITUACAO_PROTOCOLADA
    pasta = tmp_path / "resultados"
    dados = ler_planilha(planilha)
    s1 = reg.RegistroResultados(planilha, pasta, tmp_path / "backups", salvar_a_cada=99)
    s2 = reg.RegistroResultados(planilha, pasta, tmp_path / "backups", salvar_a_cada=99, sessao=2)
    s1.registrar(dados.linhas[0], SITUACAO_PAGAMENTO_REALIZADO)
    s1.registrar(dados.linhas[2], SITUACAO_PAGAMENTO_REALIZADO)
    s2.registrar(dados.linhas[1], SITUACAO_PROTOCOLADA, "Declaração enviada — nº 34450.37448.181126.1.3.19-4627")
    resultados = []
    barreira = threading.Barrier(2)

    def _gravar(r):
        barreira.wait()
        resultados.append(r.salvar())

    threads = [threading.Thread(target=_gravar, args=(r,)) for r in (s1, s2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert resultados == [True, True]
    assert _aa(planilha) == ["Situação da Verificação", SITUACAO_PAGAMENTO_REALIZADO,
                             SITUACAO_PROTOCOLADA, SITUACAO_PAGAMENTO_REALIZADO]
    assert _ab(planilha)[2] == "34450.37448.181126.1.3.19-4627"
