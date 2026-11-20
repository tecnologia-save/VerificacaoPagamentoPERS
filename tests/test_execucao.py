"""Regras do lote, com um dublê no lugar do navegador. Dados FICTÍCIOS."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from VerificacaoPagamento.certificados import Certificado
from VerificacaoPagamento.config import SITUACAO_PAGAMENTO_REALIZADO, SITUACAO_VERIFICAR
from VerificacaoPagamento.desfechos import Desfecho, EnvioSemConfirmacao
from VerificacaoPagamento.execucao import (
    MAX_REABERTURAS,
    MAX_TENTATIVAS_LINHA,
    Lote,
    executar,
    preparar_lote,
)
from VerificacaoPagamento.planilha import DadosPlanilha, LinhaPerdcomp, planejar_lote
from VerificacaoPagamento.sessao import LoginNaoConcluido, PerfilRecusado

CNPJ_A, CNPJ_B, CNPJ_C = "11111111000111", "22222222000122", "33333333000133"
PERDCOMP = "1" * 18 + "19" + "1" * 4


def _p(n: int, codigo: str = "19") -> str:
    """PER/DCOMP fictício de 24 dígitos, único por `n`, com o código de crédito."""
    return f"{n:018d}{codigo}0000"


def _linha(n, cnpj, procurador="SAVE", status="Análise concluída", tributo="PIS",
           perdcomp=None):
    # Um PER/DCOMP diferente por linha (repetidos são tratados à parte).
    perdcomp = _p(n) if perdcomp is None else perdcomp
    return LinhaPerdcomp(numero_linha=n, procurador=procurador, cnpj=cnpj, tributo=tributo,
                         empresa=f"EMPRESA {cnpj[:2]}", perdcomp=perdcomp, status=status)


def _lote(pares) -> Lote:
    nomes = {c for _, c in pares}
    return Lote(grupos=planejar_lote(pares),
                certificados={n: Certificado(n, Path(f"{n}.pfx"), "x") for n in nomes})


class _Sessao:
    def __init__(self, certificado, cnpj):
        self.certificado = certificado
        self.cnpj_ativo = cnpj
        self.perfil_real = cnpj          # o que o e-CAC mostra de verdade
        self.mensagens_importantes = False


class PortalFalso:
    """`mensagens`: CNPJs com mensagens importantes — com o popup na tela, a
    troca de perfil "dá certo" SEM trocar (o comportamento do ecac_login).
    `perfil_fixo_no_login`: certificados cujo login não troca o perfil."""

    def __init__(self, *, recusa_perfil=(), falha_login=(), derruba_linha=(), erro_linha=(),
                 mensagens=(), perfil_fixo_no_login=(), sem_confirmacao=(), tela_estranha=()):
        self.sem_confirmacao = set(sem_confirmacao)
        self.tela_estranha = set(tela_estranha)
        self.recusa_perfil = set(recusa_perfil)
        self.falha_login = set(falha_login)
        self.derruba_linha = set(derruba_linha)
        self.erro_linha = set(erro_linha)
        self.mensagens = set(mensagens)
        self.perfil_fixo_no_login = set(perfil_fixo_no_login)
        self.eventos: list[tuple] = []

    def abrir_sessao(self, certificado, cnpj):
        self.eventos.append(("login", certificado.nome, cnpj))
        if certificado.nome in self.falha_login:
            raise LoginNaoConcluido("captcha")
        if cnpj in self.recusa_perfil:
            raise PerfilRecusado("procuração expirada")
        sessao = _Sessao(certificado.nome, cnpj)
        if certificado.nome in self.perfil_fixo_no_login:
            sessao.perfil_real = "00000000000000"
        return sessao

    def trocar_empresa(self, sessao, cnpj):
        self.eventos.append(("troca", cnpj))
        if cnpj in self.recusa_perfil:
            raise PerfilRecusado("procuração expirada")
        sessao.cnpj_ativo = cnpj
        if sessao.perfil_real not in self.mensagens:  # o popup trava a troca
            sessao.perfil_real = cnpj

    def cnpj_ativo(self, sessao):
        return sessao.perfil_real

    def tem_mensagens_importantes(self, sessao):
        return sessao.perfil_real in self.mensagens

    def abrir_modulo(self, sessao):
        self.eventos.append(("modulo", sessao.perfil_real))

    def processar_linha(self, sessao, linha, *, antes_de_enviar=None):
        self.eventos.append(("linha", linha.numero_linha, sessao.perfil_real))
        if linha.numero_linha in self.derruba_linha:
            raise RuntimeError("TargetClosedError: Target page, context or browser has been closed")
        if linha.numero_linha in self.erro_linha:
            raise RuntimeError("tela inesperada")
        if antes_de_enviar is not None:
            antes_de_enviar()
        self.eventos.append(("enviar", linha.numero_linha))
        if linha.numero_linha in self.sem_confirmacao:
            raise EnvioSemConfirmacao("nenhum desfecho em 180s")
        return Desfecho(True, "pago", situacao=SITUACAO_PAGAMENTO_REALIZADO,
                        tela_conhecida=linha.numero_linha not in self.tela_estranha)

    def encerrar(self, sessao, *, navegador_morto, via_caixa_postal=False):
        self.eventos.append(("encerrar", sessao.certificado, navegador_morto, via_caixa_postal))

    def capturar(self, sessao, rotulo):
        self.eventos.append(("captura", rotulo))

    def tipos(self, tipo):
        return [e[1:] for e in self.eventos if e[0] == tipo]


def _resultado(resultados):
    return {r.numero_linha: (r.ok, r.detalhe) for r in resultados}


def test_um_navegador_por_certificado_trocando_so_o_perfil():
    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_B), "Save"),
                  (_linha(4, CNPJ_A), "Save"), (_linha(5, CNPJ_C, "D&S"), "D&S")])
    portal = PortalFalso()
    resultados = executar(lote, portal)
    assert portal.tipos("login") == [("Save", CNPJ_A), ("D&S", CNPJ_C)]
    assert portal.tipos("troca") == [(CNPJ_B,)]
    # linhas da mesma empresa ficam juntas, sempre no perfil certo
    assert portal.tipos("linha") == [(2, CNPJ_A), (4, CNPJ_A), (3, CNPJ_B), (5, CNPJ_C)]
    # sai e fecha só no fim de cada certificado
    assert portal.tipos("encerrar") == [("Save", False, False), ("D&S", False, False)]
    assert all(r.ok for r in resultados)


def test_empresa_com_mensagens_importantes_marca_a_linha_sai_pela_caixa_postal_e_segue():
    """Regra do usuário (19/11/2026): o aviso de mensagens importantes apareceu
    -> marca a linha na AA, Caixa Postal + Sair com Segurança, próxima empresa."""
    from VerificacaoPagamento.config import SITUACAO_MENSAGENS_IMPORTANTES

    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_A), "Save"),
                  (_linha(4, CNPJ_B), "Save"), (_linha(5, CNPJ_C), "Save")])
    portal = PortalFalso(mensagens={CNPJ_A})
    registro = RegistroFalso()
    resultados = _resultado(executar(lote, portal, registro=registro))
    # nenhuma linha da empresa com mensagens vai ao e-CAC
    assert all(e[1] != CNPJ_A for e in portal.tipos("linha"))
    assert (SITUACAO_MENSAGENS_IMPORTANTES, 2) in registro.anotacoes   # linha marcada
    assert resultados[2][0] and not resultados[3][0]                  # a 3 fica para o próximo passe
    assert resultados[4][0] and resultados[5][0]
    # Caixa Postal + sair; a próxima entra com login novo (sem troca)
    assert portal.tipos("encerrar") == [("Save", False, True), ("Save", False, False)]
    assert portal.tipos("login") == [("Save", CNPJ_A), ("Save", CNPJ_B)]
    assert portal.tipos("troca") == [(CNPJ_C,)]


def test_mensagens_importantes_sao_abertas_anotadas_e_a_empresa_segue():
    """Regra do usuário (19/11/2026, a nova): o aviso apareceu -> abre as
    importantes não lidas, uma linha por mensagem na aba das abertas (CNPJ,
    empresa, certificado, assunto) e as linhas da empresa seguem."""
    from VerificacaoPagamento.config import SITUACAO_MENSAGENS_IMPORTANTES

    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_A), "Save"),
                  (_linha(4, CNPJ_B), "Save")])
    portal = PortalQueAbreMensagens(mensagens={CNPJ_A})
    registro = RegistroFalso()
    resultados = _resultado(executar(lote, portal, registro=registro))
    assert all(ok for ok, _ in resultados.values())
    assert portal.tipos("abrir_mensagens") == [(CNPJ_A,)]
    mensagens = [a[1:] for a in registro.anotacoes if a[0] == "mensagem"]
    assert mensagens == [(CNPJ_A, "EMPRESA 11", "Save", "Intimação para regularizar", "901"),
                         (CNPJ_A, "EMPRESA 11", "Save", "Termo de exclusão do Simples", "902")]
    assert portal.tipos("linha") == [(2, CNPJ_A), (3, CNPJ_A), (4, CNPJ_B)]
    assert not any(a[0] == SITUACAO_MENSAGENS_IMPORTANTES for a in registro.anotacoes)
    # desbloqueada, a troca de perfil volta a valer: um login só
    assert portal.tipos("login") == [("Save", CNPJ_A)]
    assert portal.tipos("troca") == [(CNPJ_B,)]


def test_sem_conseguir_abrir_as_mensagens_vale_a_regra_antiga():
    from VerificacaoPagamento.config import SITUACAO_MENSAGENS_IMPORTANTES

    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_A), "Save"),
                  (_linha(4, CNPJ_B), "Save")])
    portal = PortalQueAbreMensagens(mensagens={CNPJ_A}, falha_ao_abrir={CNPJ_A})
    registro = RegistroFalso()
    resultados = _resultado(executar(lote, portal, registro=registro))
    assert portal.tipos("abrir_mensagens") == [(CNPJ_A,)]
    assert all(e[1] != CNPJ_A for e in portal.tipos("linha"))
    assert (SITUACAO_MENSAGENS_IMPORTANTES, 2) in registro.anotacoes
    assert resultados[2][0] and not resultados[3][0] and resultados[4][0]
    assert ("Save", False, True) in portal.tipos("encerrar")      # saiu pela Caixa Postal


def test_bloqueio_no_modulo_abre_as_mensagens_e_refaz_a_linha_sem_gastar_tentativa():
    from VerificacaoPagamento.desfechos import EmpresaBloqueadaNaCaixaPostal

    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_A), "Save")])

    class Portal(PortalQueAbreMensagens):
        bloqueada = True

        def abrir_modulo(self, sessao):
            super().abrir_modulo(sessao)
            if self.bloqueada:
                raise EmpresaBloqueadaNaCaixaPostal("Caixa Postal no lugar do PER/DCOMP")

        def abrir_mensagens_importantes(self, sessao, cnpj, *, ao_abrir):
            self.bloqueada = False
            return super().abrir_mensagens_importantes(sessao, cnpj, ao_abrir=ao_abrir)

    portal = Portal()
    registro = RegistroFalso()
    resultados = _resultado(executar(lote, portal, registro=registro))
    assert resultados[2][0] and resultados[3][0]
    assert portal.tipos("abrir_mensagens") == [(CNPJ_A,)]
    assert portal.tipos("linha") == [(2, CNPJ_A), (3, CNPJ_A)]
    assert portal.tipos("modulo").count((CNPJ_A,)) == 2      # bloqueado, depois liberado


def test_mensagens_que_continuam_travando_sao_tentadas_uma_vez_so():
    from VerificacaoPagamento.config import SITUACAO_MENSAGENS_IMPORTANTES
    from VerificacaoPagamento.desfechos import EmpresaBloqueadaNaCaixaPostal

    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_A), "Save")])

    class Portal(PortalQueAbreMensagens):
        def abrir_modulo(self, sessao):
            super().abrir_modulo(sessao)
            raise EmpresaBloqueadaNaCaixaPostal("Caixa Postal no lugar do PER/DCOMP")

    portal = Portal()
    registro = RegistroFalso()
    executar(lote, portal, registro=registro)
    assert portal.tipos("abrir_mensagens") == [(CNPJ_A,)]
    assert (SITUACAO_MENSAGENS_IMPORTANTES, 2) in registro.anotacoes
    assert portal.tipos("linha") == []


def test_procuracao_sem_poder_para_o_perdcomp_marca_a_empresa_e_segue():
    from VerificacaoPagamento.config import SITUACAO_SEM_PERMISSAO
    from VerificacaoPagamento.desfechos import SemPermissaoPerdcomp

    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_A), "Save"),
                  (_linha(4, CNPJ_B), "Save")])

    class Portal(PortalFalso):
        def abrir_modulo(self, sessao):
            super().abrir_modulo(sessao)
            if sessao.perfil_real == CNPJ_A:
                raise SemPermissaoPerdcomp("perfil sem permissão")

    portal = Portal()
    registro = RegistroFalso()
    resultados = _resultado(executar(lote, portal, registro=registro))
    assert (SITUACAO_SEM_PERMISSAO, 2) in registro.anotacoes
    assert (SITUACAO_SEM_PERMISSAO, 3) in registro.anotacoes
    assert all(resultados[n][0] for n in (2, 3, 4))
    assert portal.tipos("linha") == [(4, CNPJ_B)]
    assert portal.tipos("modulo").count((CNPJ_A,)) == 1        # sem retentativas


def test_rede_na_troca_de_perfil_reabre_o_navegador_e_nao_descarta_a_empresa():
    """19/11/2026: net::ERR_BLOCKED_BY_CLIENT na troca de perfil derrubou 192
    linhas como "perfil recusado". É a rede: fecha, espera e abre de novo."""
    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_B), "Save"),
                  (_linha(4, CNPJ_C), "Save")])

    class Portal(PortalFalso):
        quebrado = True
        esperas = 0

        def trocar_empresa(self, sessao, cnpj):
            if self.quebrado:
                self.quebrado = False
                self.eventos.append(("troca", cnpj))
                raise LoginNaoConcluido("rede na troca de perfil — PortalIndisponivel: "
                                        "Page.goto: net::ERR_BLOCKED_BY_CLIENT")
            super().trocar_empresa(sessao, cnpj)

        def aguardar_rede(self):
            self.esperas += 1

    portal = Portal()
    resultados = _resultado(executar(lote, portal))
    assert all(ok for ok, _ in resultados.values())
    assert portal.tipos("linha") == [(2, CNPJ_A), (3, CNPJ_B), (4, CNPJ_C)]
    assert portal.tipos("login") == [("Save", CNPJ_A), ("Save", CNPJ_B)]   # reabriu
    assert portal.esperas == 1


def test_troca_que_nao_trocou_faz_login_novo_e_nunca_preenche_no_cnpj_errado():
    """O popup apareceu DEPOIS da conferência na entrada (não detectado): a
    troca do ecac_login 'dá certo' sem trocar. A conferência do perfil pega."""
    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_B), "Save")])
    portal = PortalFalso(mensagens={CNPJ_A})
    portal.tem_mensagens_importantes = lambda sessao: False  # popup não visto na entrada
    resultados = _resultado(executar(lote, portal))
    assert resultados[3][0]
    assert portal.tipos("linha") == [(2, CNPJ_A), (3, CNPJ_B)]
    assert portal.tipos("login") == [("Save", CNPJ_A), ("Save", CNPJ_B)]
    assert ("perfil_divergente_" + CNPJ_B,) in portal.tipos("captura")


def test_login_que_nao_ativa_o_perfil_nao_processa_e_desiste_do_certificado():
    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_B), "Save"),
                  (_linha(4, CNPJ_C), "Save")])
    portal = PortalFalso(perfil_fixo_no_login={"Save"})
    resultados = _resultado(executar(lote, portal))
    assert not any(ok for ok, _ in resultados.values())
    assert portal.tipos("linha") == []
    # 2 empresas seguidas sem entrar (cada uma insistindo MAX_REABERTURAS vezes) -> desiste
    assert len(portal.tipos("login")) == 2 * MAX_REABERTURAS
    assert "não concluído" in resultados[4][1]


def test_empresa_recusada_nao_derruba_as_outras_do_certificado():
    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_B), "Save"),
                  (_linha(4, CNPJ_B), "Save"), (_linha(5, CNPJ_C), "Save")])
    portal = PortalFalso(recusa_perfil={CNPJ_B})
    resultados = _resultado(executar(lote, portal))
    assert resultados[2][0] and resultados[5][0]
    assert not resultados[3][0] and "procuração expirada" in resultados[3][1]
    assert not resultados[4][0]
    assert portal.tipos("troca") == [(CNPJ_B,), (CNPJ_C,)]


def test_perfil_recusado_no_primeiro_login_tenta_a_proxima_empresa_com_novo_login():
    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_B), "Save")])
    portal = PortalFalso(recusa_perfil={CNPJ_A})
    resultados = _resultado(executar(lote, portal))
    assert portal.tipos("login") == [("Save", CNPJ_A), ("Save", CNPJ_B)]
    assert (resultados[2][0], resultados[3][0]) == (False, True)


def test_login_que_falha_duas_vezes_desiste_do_certificado_e_segue():
    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_B), "Save"),
                  (_linha(4, CNPJ_C), "Save"), (_linha(5, CNPJ_A, "D&S"), "D&S")])
    portal = PortalFalso(falha_login={"Save"})
    resultados = _resultado(executar(lote, portal))
    # cada empresa insiste MAX_REABERTURAS vezes antes de contar uma falha de login
    assert portal.tipos("login") == ([("Save", CNPJ_A)] * MAX_REABERTURAS
                                     + [("Save", CNPJ_B)] * MAX_REABERTURAS + [("D&S", CNPJ_A)])
    assert [resultados[n][0] for n in (2, 3, 4, 5)] == [False, False, False, True]


def test_navegador_que_cai_reabre_na_linha_seguinte():
    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_A), "Save")])
    portal = PortalFalso(derruba_linha={2})
    resultados = _resultado(executar(lote, portal))
    assert (resultados[2][0], resultados[3][0]) == (False, True)
    assert ("Save", True, False) in portal.tipos("encerrar")
    # linha 2: todas as tentativas, cada uma num login novo (o navegador caiu); linha 3: mais um
    assert portal.tipos("login") == [("Save", CNPJ_A)] * (MAX_TENTATIVAS_LINHA + 1)


def test_erro_de_tela_salva_a_tela_e_segue_na_mesma_sessao():
    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_A), "Save")])
    portal = PortalFalso(erro_linha={2})
    resultados = _resultado(executar(lote, portal))
    assert (resultados[2][0], resultados[3][0]) == (False, True)
    assert portal.tipos("captura") == [("erro_linha_2",)] * MAX_TENTATIVAS_LINHA
    assert len(portal.tipos("login")) == 1
    # cada tentativa (e a linha seguinte) recomeça com o módulo recarregado
    assert portal.tipos("modulo") == [(CNPJ_A,)] * (MAX_TENTATIVAS_LINHA + 1)


class _Parada(BaseException):
    pass


def test_parada_do_operador_sai_com_seguranca_e_guarda_o_parcial():
    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_A), "Save")])
    portal = PortalFalso()
    chamadas = {"n": 0}

    def checkpoint():
        chamadas["n"] += 1
        if chamadas["n"] == 3:  # empresa, linha 2, linha 3 <- aqui
            raise _Parada()

    parcial = []
    with pytest.raises(_Parada):
        executar(lote, portal, checkpoint=checkpoint, resultados=parcial)
    assert [r.numero_linha for r in parcial] == [2]
    assert portal.tipos("encerrar") == [("Save", False, False)]


# ── preparar_lote ────────────────────────────────────────────────────────────

def test_empresas_prioritarias_vem_antes_de_todas_as_outras(tmp_path):
    from tests.test_certificados import _pfx
    from VerificacaoPagamento.certificados import ler_senhas, listar_pfx

    for nome in ("Save Inteligência", "D&S"):
        _pfx(tmp_path / f"{nome}.pfx", "s")
    (tmp_path / "senhas.json").write_text(json.dumps({"Save Inteligência.pfx": "s", "D&S.pfx": "s"}),
                                          encoding="utf-8")
    outra_a, outra_b = "44444444000144", "55555555000155"
    linhas = [
        _linha(2, outra_a, "SAVE", status="Em análise"),       # Save, não prioritária
        _linha(3, CNPJ_A, "SAVE"),                              # Save, prioritária
        _linha(4, outra_b, "D&S", status="Em análise"),        # D&S, não prioritária
        _linha(5, CNPJ_B, "D&S"),                               # D&S, prioritária
    ]
    dados = DadosPlanilha(caminho="x.xlsx", nome_aba="a", linhas=linhas, tem_coluna_situacao=True)
    lote = preparar_lote(dados, None, listar_pfx(tmp_path), ler_senhas(tmp_path / "senhas.json"))
    ordem = [(g.certificado, ln.numero_linha) for g in lote.grupos for e in g.empresas
             for ln in e.linhas]
    assert [n for _, n in ordem] == [3, 5, 4, 2]
    assert [g.certificado for g in lote.grupos] == ["Save Inteligência", "D&S", "Save Inteligência"]


def test_preparar_lote_filtra_e_agrega_os_problemas(tmp_path):
    from tests.test_certificados import _pfx

    _pfx(tmp_path / "Save Inteligência.pfx", "s")
    _pfx(tmp_path / "D&S.pfx", "s")
    (tmp_path / "senhas.json").write_text(json.dumps({"Save Inteligência.pfx": "s",
                                                      "D&S.pfx": "errada"}), encoding="utf-8")
    from VerificacaoPagamento.certificados import ler_senhas, listar_pfx

    linhas = [
        _linha(2, CNPJ_A, "Save Inteligencia"),                   # entra
        _linha(3, CNPJ_A, "SAVE", status="Em análise"),           # entra: a empresa é prioritária
        _linha(12, "44444444000144", "SAVE", status="Em análise"),  # entra DEPOIS: sem 'Análise concluída'
        _linha(4, CNPJ_B, "ELIANE"),                              # ignorado — só log
        _linha(5, CNPJ_B, "MARIA"),                               # sem certificado
        _linha(6, "", "SAVE"),                                    # CNPJ inválido
        _linha(7, CNPJ_C, "SAVE", tributo="2024"),                # tributo fora
        _linha(8, CNPJ_C, "SAVE", tributo="PIS/COFINS"),          # tributo ambíguo
        _linha(9, CNPJ_C, "SAVE", perdcomp="123"),                # PER/DCOMP inválido
        _linha(10, CNPJ_C, "D&S"),                                # senha errada
        _linha(11, CNPJ_C, "SAVE", tributo="COFINS/FASE"),        # entra (COFINS)
    ]
    dados = DadosPlanilha(caminho="x.xlsx", nome_aba="a", linhas=linhas, tem_coluna_situacao=True)
    lote = preparar_lote(dados, None, listar_pfx(tmp_path), ler_senhas(tmp_path / "senhas.json"))

    assert [ln.numero_linha for g in lote.grupos for e in g.empresas for ln in e.linhas] == [2, 3, 11, 12]
    assert len(lote.grupos) == 1                      # mesmo certificado: um login só
    texto = " | ".join(lote.avisos)
    assert "ELIANE" not in texto and "Em análise" not in texto
    assert "procurador 'MARIA'" in texto
    assert "CNPJ inválido" in texto
    assert "tributo fora de PIS/COFINS" in texto and "'2024'" in texto and "'PIS/COFINS'" in texto
    assert "24 dígitos" in texto
    assert "certificado 'D&S'" in texto and "não abre" in texto
    infos = " | ".join(lote.informacoes)
    assert "1 linha(s) de outras empresas vêm depois delas" in infos
    assert "1 linha(s) de procurador ignorado" in infos


def test_limite_conta_as_primeiras_linhas_que_passaram_nos_filtros(monkeypatch):
    linhas = [_linha(n, CNPJ_A) for n in range(2, 12)]
    linhas[0].situacao_verificacao = "Concluído"
    linhas[1].status = "Em análise"
    dados = DadosPlanilha(caminho="x.xlsx", nome_aba="a", linhas=linhas, tem_coluna_situacao=True)
    pfx = {"save inteligencia": Path("Save Inteligência.pfx")}

    from VerificacaoPagamento import execucao

    monkeypatch.setattr(execucao, "carregar_certificado",
                        lambda caminho, senhas: Certificado(caminho.stem, caminho, "x"))
    lote = preparar_lote(dados, 3, pfx, {})
    # a linha 3 ("Em análise") entra: a empresa tem 'Análise concluída'
    assert [ln.numero_linha for g in lote.grupos for e in g.empresas for ln in e.linhas] == [3, 4, 5]


def test_limite_de_empresas_corta_na_ordem_do_robo(monkeypatch):
    from VerificacaoPagamento import execucao

    monkeypatch.setattr(execucao, "carregar_certificado",
                        lambda caminho, senhas: Certificado(caminho.stem, caminho, "x"))
    linhas = [_linha(2, CNPJ_A, "D&S"), _linha(3, CNPJ_B, "SAVE"), _linha(4, CNPJ_C, "D&S"),
              _linha(5, CNPJ_A, "D&S", status="Em análise")]
    dados = DadosPlanilha(caminho="x.xlsx", nome_aba="a", linhas=linhas, tem_coluna_situacao=True)
    pfx = {"save inteligencia": Path("Save Inteligência.pfx"), "d&s": Path("D&S.pfx")}
    lote = preparar_lote(dados, None, pfx, {}, limite_empresas=1)
    # a 1ª empresa do robô: D&S (1º certificado da planilha), CNPJ_A, inteira
    assert [(g.certificado, e.cnpj, [ln.numero_linha for ln in e.linhas])
            for g in lote.grupos for e in g.empresas] == [("D&S", CNPJ_A, [2, 5])]
    assert list(lote.certificados) == ["D&S"]
    lote = preparar_lote(dados, None, pfx, {}, limite_empresas=2)
    assert [e.cnpj for g in lote.grupos for e in g.empresas] == [CNPJ_A, CNPJ_C]


# ── Desfechos, registro e quarentena ─────────────────────────────────────────

class RegistroFalso:
    def __init__(self, portal=None):
        self.portal = portal
        self.anotacoes: list[tuple] = []

    def marcar_envio(self, linha):
        self.anotacoes.append(("enviando", linha.numero_linha))
        if self.portal is not None:  # a ordem importa: ANTES do clique
            assert ("enviar", linha.numero_linha) not in self.portal.eventos

    def registrar(self, linha, situacao, detalhe=""):
        self.anotacoes.append((situacao, linha.numero_linha))

    def registrar_mensagem(self, *, cnpj, empresa, certificado, assunto, isn):
        self.anotacoes.append(("mensagem", cnpj, empresa, certificado, assunto, isn))


class PortalQueAbreMensagens(PortalFalso):
    """Abre as mensagens importantes na Caixa Postal: `falha_ao_abrir` = CNPJs
    em que não dá (a regra antiga vale)."""

    def __init__(self, *, falha_ao_abrir=(), **kw):
        super().__init__(**kw)
        self.falha_ao_abrir = set(falha_ao_abrir)

    def abrir_mensagens_importantes(self, sessao, cnpj, *, ao_abrir):
        self.eventos.append(("abrir_mensagens", cnpj))
        if cnpj in self.falha_ao_abrir:
            raise RuntimeError("filtro da Caixa Postal sem resposta")
        ao_abrir("901", "Intimação para regularizar")
        ao_abrir("902", "Termo de exclusão do Simples")
        self.mensagens.discard(cnpj)          # o aviso some
        return 2


def test_desfecho_vai_para_o_registro_e_a_proxima_linha_segue_pelo_novo_documento():
    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_A), "Save"),
                  (_linha(4, CNPJ_A), "Save")])
    portal = PortalFalso(tela_estranha={3})
    registro = RegistroFalso(portal)
    executar(lote, portal, registro=registro)
    assert registro.anotacoes == [("enviando", 2), (SITUACAO_PAGAMENTO_REALIZADO, 2),
                                  ("enviando", 3), (SITUACAO_PAGAMENTO_REALIZADO, 3),
                                  ("enviando", 4), (SITUACAO_PAGAMENTO_REALIZADO, 4)]
    # módulo aberto 1x para a 2 e 3 (tela conhecida); a 3 deixou tela estranha -> recarrega
    assert portal.tipos("modulo") == [(CNPJ_A,), (CNPJ_A,)]


def test_modo_seguro_sem_registro_nada_e_anotado():
    lote = _lote([(_linha(2, CNPJ_A), "Save")])
    resultados = executar(lote, PortalFalso(), registro=None)
    assert resultados[0].ok


def test_envio_sem_confirmacao_vai_para_quarentena_e_o_lote_segue():
    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_A), "Save")])
    portal = PortalFalso(sem_confirmacao={2})
    registro = RegistroFalso()
    resultados = _resultado(executar(lote, portal, registro=registro))
    assert (SITUACAO_VERIFICAR, 2) in registro.anotacoes
    assert not resultados[2][0] and resultados[2][1].startswith(SITUACAO_VERIFICAR)
    assert resultados[3][0]


def test_envios_sem_confirmacao_nao_param_e_nunca_sao_reenviados():
    """Rodando 24 h sem parar (pedido do usuário): cada envio sem confirmação
    fica na quarentena, sem reenvio, e o lote segue."""
    lote = _lote([(_linha(n, CNPJ_A), "Save") for n in range(2, 7)])
    portal = PortalFalso(sem_confirmacao={2, 3, 4})
    registro = RegistroFalso()
    resultados = _resultado(executar(lote, portal, registro=registro))
    assert [n for s, n in registro.anotacoes if s == SITUACAO_VERIFICAR] == [2, 3, 4]
    assert portal.tipos("enviar") == [(2,), (3,), (4,), (5,), (6,)]  # um Enviar por linha
    assert resultados[5][0] and resultados[6][0]


def test_instabilidade_passageira_e_vencida_refazendo_a_linha():
    """'Não é possível prosseguir neste momento' numa tentativa: a linha é
    refeita do zero, com o módulo recarregado, e passa."""
    lote = _lote([(_linha(2, CNPJ_A), "Save")])
    portal = PortalFalso()
    original = portal.processar_linha
    falhas = {"n": 1}

    def instavel(sessao, linha, *, antes_de_enviar=None):
        if falhas["n"]:
            falhas["n"] -= 1
            portal.eventos.append(("linha", linha.numero_linha, sessao.perfil_real))
            raise RuntimeError("Nao e possivel prosseguir neste momento")
        return original(sessao, linha, antes_de_enviar=antes_de_enviar)

    portal.processar_linha = instavel
    registro = RegistroFalso()
    resultados = executar(lote, portal, registro=registro)
    assert [r.ok for r in resultados] == [True]          # um resultado só, o bom
    assert registro.anotacoes == [("enviando", 2), (SITUACAO_PAGAMENTO_REALIZADO, 2)]
    assert portal.tipos("modulo") == [(CNPJ_A,), (CNPJ_A,)]


def test_envio_sem_confirmacao_nunca_e_refeito():
    lote = _lote([(_linha(2, CNPJ_A), "Save")])
    portal = PortalFalso(sem_confirmacao={2})
    executar(lote, portal, registro=RegistroFalso())
    assert portal.tipos("enviar") == [(2,)]               # um Enviar só


def test_envio_recusado_pelo_servidor_e_refeito_e_anulado_no_diario():
    from VerificacaoPagamento.desfechos import EnvioRecusadoPeloServidor

    lote = _lote([(_linha(2, CNPJ_A), "Save")])
    portal = PortalFalso()
    original = portal.processar_linha
    recusas = {"n": 1}

    def recusa_uma_vez(sessao, linha, *, antes_de_enviar=None):
        if recusas["n"]:
            recusas["n"] -= 1
            antes_de_enviar()
            raise EnvioRecusadoPeloServidor("Nao e possivel prosseguir neste momento")
        return original(sessao, linha, antes_de_enviar=antes_de_enviar)

    portal.processar_linha = recusa_uma_vez

    class Registro(RegistroFalso):
        def marcar_nao_transmitido(self, linha, detalhe=""):
            self.anotacoes.append(("nao_transmitido", linha.numero_linha))

    registro = Registro()
    resultados = executar(lote, portal, registro=registro)
    assert [r.ok for r in resultados] == [True]
    assert registro.anotacoes == [("enviando", 2), ("nao_transmitido", 2),
                                  ("enviando", 2), (SITUACAO_PAGAMENTO_REALIZADO, 2)]


def test_perdcomp_repetido_na_planilha_vai_uma_vez_so_ao_ecac(monkeypatch):
    from VerificacaoPagamento import execucao

    monkeypatch.setattr(execucao, "carregar_certificado",
                        lambda caminho, senhas: Certificado(caminho.stem, caminho, "x"))
    linhas = [_linha(2, CNPJ_A, perdcomp=_p(1)), _linha(3, CNPJ_A, perdcomp=_p(2)),
              _linha(4, CNPJ_A, perdcomp=_p(1))]
    dados = DadosPlanilha(caminho="x.xlsx", nome_aba="a", linhas=linhas, tem_coluna_situacao=True)
    lote = preparar_lote(dados, None, {"save inteligencia": Path("Save Inteligência.pfx")}, {})
    assert [ln.numero_linha for g in lote.grupos for e in g.empresas for ln in e.linhas] == [2, 3]
    assert any("repetem o PER/DCOMP" in i for i in lote.informacoes)


def test_aviso_da_transmissao_so_e_fechado_depois_de_gravado():
    """Pedido do usuário (18/11/2026): o "X" do aviso "TEVE O PAGAMENTO
    REALIZADO" só depois de confirmar o aviso E gravar o resultado."""
    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_A), "Save")])
    registro = RegistroFalso()

    class PortalComAviso(PortalFalso):
        def processar_linha(self, sessao, linha, *, antes_de_enviar=None):
            desfecho = super().processar_linha(sessao, linha, antes_de_enviar=antes_de_enviar)

            def fechar():
                registro.anotacoes.append(("x", linha.numero_linha))
                if linha.numero_linha == 3:
                    raise RuntimeError("X sumiu")
            desfecho.depois_de_gravar = fechar
            return desfecho

    portal = PortalComAviso()
    resultados = _resultado(executar(lote, portal, registro=registro))
    assert [a for a in registro.anotacoes if a[0] != "enviando"] == [
        (SITUACAO_PAGAMENTO_REALIZADO, 2), ("x", 2), (SITUACAO_PAGAMENTO_REALIZADO, 3), ("x", 3)]
    assert resultados[2][0] and resultados[3][0]   # falha no X não estraga o resultado


def test_duas_sessoes_divididas_por_certificado_sem_perdcomp_nas_duas(monkeypatch):
    """Duas sessões ao mesmo tempo (18/11/2026): uma só com o Save Inteligência,
    a outra com os demais. Um PER/DCOMP repetido em certificados diferentes vai
    só para a sessão da PRIMEIRA linha — nunca para as duas."""
    from VerificacaoPagamento import execucao

    monkeypatch.setattr(execucao, "carregar_certificado",
                        lambda caminho, senhas: Certificado(caminho.stem, caminho, "x"))
    linhas = [_linha(2, CNPJ_A, "SAVE"), _linha(3, CNPJ_B, "D&S"), _linha(4, CNPJ_C, "GHS"),
              _linha(5, CNPJ_B, "D&S", perdcomp=_p(2)),                # repete a linha 2
              _linha(6, CNPJ_A, "SAVE")]
    dados = DadosPlanilha(caminho="x.xlsx", nome_aba="a", linhas=linhas, tem_coluna_situacao=True)
    pfx = {"save inteligencia": Path("Save Inteligência.pfx"), "d&s": Path("D&S.pfx"),
           "gsh": Path("GSH.pfx")}

    def _linhas(lote):
        return sorted(ln.numero_linha for g in lote.grupos for e in g.empresas for ln in e.linhas)

    sessao1 = preparar_lote(dados, None, pfx, {}, certificados_incluidos=["Save Inteligência"])
    sessao2 = preparar_lote(dados, None, pfx, {}, certificados_excluidos=["save inteligencia"])
    assert _linhas(sessao1) == [2, 6]
    assert _linhas(sessao2) == [3, 4]
    assert set(sessao1.certificados) == {"Save Inteligência"}
    assert set(sessao2.certificados) == {"D&S", "GSH"}
    assert not sessao1.avisos and not sessao2.avisos
    errado = preparar_lote(dados, None, pfx, {}, certificados_incluidos=["Save Inteligencia X"])
    assert _linhas(errado) == [] and errado.avisos


def test_restituicao_fica_fora_do_lote_pelo_numero_do_perdcomp(monkeypatch):
    """Linha 537 (18/11/2026): PER/DCOMP 05507.32579.220926.1.2.04-0646 é de
    restituição (crédito 04) — a Receita recusa PIS e COFINS. Só entram os
    créditos 18/19 (ressarcimento PIS/COFINS), qualquer que seja a coluna H."""
    from VerificacaoPagamento import execucao

    monkeypatch.setattr(execucao, "carregar_certificado",
                        lambda caminho, senhas: Certificado(caminho.stem, caminho, "x"))
    linhas = [_linha(2, CNPJ_A, perdcomp="055073257922092612040646"),   # restituição: fora
              _linha(3, CNPJ_A, perdcomp=_p(3, "18")),
              _linha(4, CNPJ_A, perdcomp=_p(4, "19")),
              _linha(5, CNPJ_A, perdcomp=_p(5, "04"))]
    dados = DadosPlanilha(caminho="x.xlsx", nome_aba="a", linhas=linhas, tem_coluna_situacao=True)
    lote = preparar_lote(dados, None, {"save inteligencia": Path("Save Inteligência.pfx")}, {})
    assert [ln.numero_linha for g in lote.grupos for e in g.empresas for ln in e.linhas] == [3, 4]
    assert any("2 linha(s) com PER/DCOMP de outro tipo de crédito" in a for a in lote.avisos)


def test_tipo_de_credito_recusado_nos_dois_tributos_nao_e_refeito():
    from VerificacaoPagamento.desfechos import TipoCreditoDivergente

    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_A), "Save")])

    class PortalRecusaTipo(PortalFalso):
        def processar_linha(self, sessao, linha, *, antes_de_enviar=None):
            if linha.numero_linha == 2:
                self.eventos.append(("linha", 2, sessao.perfil_real))
                raise TipoCreditoDivergente("tipo diferente nos dois tributos")
            return super().processar_linha(sessao, linha, antes_de_enviar=antes_de_enviar)

    portal = PortalRecusaTipo()
    resultados = _resultado(executar(lote, portal))
    assert [e for e in portal.tipos("linha") if e[0] == 2] == [(2, CNPJ_A)]   # uma vez só
    assert not resultados[2][0] and "TipoCreditoDivergente" in resultados[2][1]
    assert resultados[3][0]


def test_sessao_que_nao_reabre_insiste_na_hora_em_vez_de_largar_a_empresa():
    """Pedido do usuário (18/11/2026): navegador que fechou abre de novo na hora."""
    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_A), "Save")])

    class PortalInstavel(PortalFalso):
        falhas = 2

        def abrir_sessao(self, certificado, cnpj):
            if self.falhas:
                self.falhas -= 1
                self.eventos.append(("login", certificado.nome, cnpj))
                raise RuntimeError("TargetClosedError: browser has been closed")
            return super().abrir_sessao(certificado, cnpj)

    portal = PortalInstavel()
    resultados = _resultado(executar(lote, portal))
    assert resultados[2][0] and resultados[3][0]
    assert portal.tipos("login") == [("Save", CNPJ_A)] * 3


def test_queda_de_rede_espera_o_portal_sem_gastar_as_tentativas():
    """18/11/2026: ERR_SOCKS_CONNECTION_FAILED por ~5 min a cada ~30 min. A
    linha espera o portal voltar e é feita — não fica para o próximo passe."""
    lote = _lote([(_linha(2, CNPJ_A), "Save")])

    class PortalQueCai(PortalFalso):
        quedas = MAX_TENTATIVAS_LINHA + 2     # mais quedas que tentativas
        esperas = 0

        def aguardar_rede(self):
            self.esperas += 1

        def processar_linha(self, sessao, linha, *, antes_de_enviar=None):
            if self.quedas:
                self.quedas -= 1
                raise RuntimeError("Error: Page.goto: net::ERR_SOCKS_CONNECTION_FAILED at https://cav")
            return super().processar_linha(sessao, linha, antes_de_enviar=antes_de_enviar)

    portal = PortalQueCai()
    resultados = _resultado(executar(lote, portal))
    assert resultados[2][0]
    assert portal.esperas == MAX_TENTATIVAS_LINHA + 2
    assert len(portal.tipos("login")) == 1          # mesmo navegador o tempo todo


def test_empresa_bloqueada_na_caixa_postal_e_pulada_na_hora():
    """AGROFEG (18/11/2026): mensagem importante não lida -> o e-CAC abre a
    Caixa Postal no lugar do PER/DCOMP. Sem retentativas, sem abrir mensagem:
    as linhas da empresa ficam para o próximo passe e a próxima empresa segue
    com login novo (saindo pela Caixa Postal)."""
    from VerificacaoPagamento.desfechos import EmpresaBloqueadaNaCaixaPostal

    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_A), "Save"),
                  (_linha(4, CNPJ_A), "Save"), (_linha(5, CNPJ_B), "Save")])

    class PortalComBloqueio(PortalFalso):
        def abrir_modulo(self, sessao):
            super().abrir_modulo(sessao)
            if sessao.perfil_real == CNPJ_A:
                raise EmpresaBloqueadaNaCaixaPostal("Caixa Postal no lugar do PER/DCOMP")

    portal = PortalComBloqueio()
    registro = RegistroFalso()
    resultados = _resultado(executar(lote, portal, registro=registro))
    # a linha em que apareceu é marcada; as outras da empresa ficam para depois
    assert [resultados[n][0] for n in (2, 3, 4, 5)] == [True, False, False, True]
    assert all("Caixa Postal" in resultados[n][1] for n in (2, 3, 4))
    from VerificacaoPagamento.config import SITUACAO_MENSAGENS_IMPORTANTES
    assert (SITUACAO_MENSAGENS_IMPORTANTES, 2) in registro.anotacoes
    assert portal.tipos("modulo").count((CNPJ_A,)) == 1          # uma vez só, sem retentativas
    assert ("Save", False, True) in portal.tipos("encerrar")     # saiu pela Caixa Postal
    assert portal.tipos("login") == [("Save", CNPJ_A), ("Save", CNPJ_B)]


def test_das_1h_as_3h_sai_com_seguranca_espera_e_retoma_as_3h01(monkeypatch):
    """Receitanet fora das 1h às 3h (19/11/2026): nenhuma linha começa nesse
    horário; a sessão sai com segurança e volta às 3h01."""
    from datetime import datetime as dt

    from VerificacaoPagamento import execucao

    relogio = {"agora": dt(2026, 11, 19, 0, 50)}
    dormidas = []

    def dormir(s):
        dormidas.append(s)
        relogio["agora"] = relogio["agora"] + execucao.timedelta(seconds=s)

    monkeypatch.setattr(execucao, "_agora", lambda: relogio["agora"])
    monkeypatch.setattr(execucao, "_dormir", dormir)

    lote = _lote([(_linha(2, CNPJ_A), "Save"), (_linha(3, CNPJ_A), "Save")])

    class PortalNoite(PortalFalso):
        def processar_linha(self, sessao, linha, *, antes_de_enviar=None):
            self.eventos.append(("hora", linha.numero_linha, relogio["agora"].strftime("%H:%M")))
            if linha.numero_linha == 2:
                relogio["agora"] = dt(2026, 11, 19, 0, 59)   # a linha 2 terminou às 0h59
            return super().processar_linha(sessao, linha, antes_de_enviar=antes_de_enviar)

    portal = PortalNoite()
    resultados = _resultado(executar(lote, portal))
    assert resultados[2][0] and resultados[3][0]
    horas = {n: h for n, h in portal.tipos("hora")}
    assert horas[2] == "00:50"
    assert horas[3] >= "03:01"                       # a linha 3 só depois das 3h01
    assert ("Save", False, False) in portal.tipos("encerrar")   # saiu com segurança
    assert portal.tipos("login") == [("Save", CNPJ_A), ("Save", CNPJ_A)]  # login novo às 3h01
    assert sum(dormidas) >= 2 * 3600 - 60


def test_janela_receitanet_limites():
    from datetime import datetime as dt

    from VerificacaoPagamento.execucao import na_janela_receitanet
    assert not na_janela_receitanet(dt(2026, 11, 19, 0, 57))
    assert na_janela_receitanet(dt(2026, 11, 19, 0, 58))
    assert na_janela_receitanet(dt(2026, 11, 19, 2, 30))
    assert na_janela_receitanet(dt(2026, 11, 19, 3, 0, 59))
    assert not na_janela_receitanet(dt(2026, 11, 19, 3, 1))
