"""O que a orquestração (`execucao.executar`) pede ao navegador, de verdade."""
from __future__ import annotations

import time
from pathlib import Path

from . import caixa_postal as _caixa_postal
from . import rascunhos as _rascunhos
from . import sessao as _sessao
from .certificados import Certificado
from .config import (
    PERMITIR_ACOES_REAIS_NO_ECAC,
    SITUACAO_PERDCOMP_CANCELADO,
    SITUACAO_TIPO_CREDITO_DIVERGENTE,
)
from .desfechos import (
    Desfecho,
    EmpresaBloqueadaNaCaixaPostal,
    EnvioRecusadoPeloServidor,
    EnvioSemConfirmacao,
    PerdcompCancelado,
    SemPermissaoPerdcomp,
    TipoCreditoDivergente,
)
from .diagnostico import capturar_tela
from .etapas_dcomp import concluir_declaracao
from .formulario_perdcomp import (
    TelaNovoDocumentoIndisponivel,
    navegador_fechou,
    conferencias_identificacao,
    instalar_rastreador,
    preencher_identificacao,
)
from .navegacao import navegar_modulo_perdcomp
from .formulario_perdcomp import TEXTO_TIPO_CREDITO
from .planilha import TRIBUTO_COFINS, TRIBUTO_PIS, TRIBUTOS_CREDITO_EM_ABAS, LinhaPerdcomp

# Pausa depois que a sonda diz que o e-CAC voltou, antes de refazer a linha.
ESPERA_ERRO_REDE_S = 30


class PerfilDivergente(Exception):
    """O perfil ativo no e-CAC não é o CNPJ da linha: nada é preenchido."""


class PortalReal:
    def __init__(self, *, project_dir: Path, perfil_dir: Path | None, pasta_debug: Path,
                 checkpoint=None, cancelado=None, navegador_aberto: bool = False) -> None:
        self._project_dir = project_dir
        self._perfil_dir = perfil_dir
        self._pasta_debug = pasta_debug
        self._checkpoint = checkpoint
        self._cancelado = cancelado
        self._navegador_aberto = navegador_aberto

    # ── sessão ───────────────────────────────────────────────────────────────
    def abrir_sessao(self, certificado: Certificado, cnpj: str) -> _sessao.Sessao:
        if self._navegador_aberto:
            # Reaproveita o Chrome já logado (manter_navegador.py): sem login,
            # só a troca de perfil. Sem navegador aberto, NÃO cai para um login
            # novo em silêncio — o operador pediu para usar o mesmo.
            print(f"ETAPA: Navegador aberto — CNPJ {cnpj}")
            sessao = _sessao.conectar_navegador_aberto()
            if sessao is None:
                raise _sessao.LoginNaoConcluido(
                    "nenhum navegador aberto e logado no e-CAC (rode manter_navegador.py)")
            instalar_rastreador(sessao.page)
            if sessao.cnpj_ativo != cnpj:
                _sessao.trocar_empresa(sessao, cnpj)
            print("LOGIN CONCLUIDO (navegador aberto reaproveitado)")
            return sessao
        print(f"ETAPA: Login no eCAC — certificado '{certificado.nome}', CNPJ {cnpj}")
        sessao = _sessao.abrir_sessao(
            certificado, cnpj, project_dir=self._project_dir, perfil_dir=self._perfil_dir,
            checkpoint=self._checkpoint, cancelado=self._cancelado,
        )
        print("LOGIN CONCLUIDO")
        # Acompanha as requisições da página: as esperas antes de cada campo e
        # de cada avanço só seguem com o servidor quieto (ver RastreadorRede).
        instalar_rastreador(sessao.page)
        return sessao

    def trocar_empresa(self, sessao: _sessao.Sessao, cnpj: str) -> None:
        _sessao.trocar_empresa(sessao, cnpj)
        print("  -> Perfil alterado.")

    def cnpj_ativo(self, sessao: _sessao.Sessao) -> str:
        return _sessao.cnpj_do_perfil_ativo(sessao.page)

    def tem_mensagens_importantes(self, sessao: _sessao.Sessao) -> bool:
        return _sessao.tem_mensagens_importantes(sessao.page)

    def encerrar(self, sessao: _sessao.Sessao, *, navegador_morto: bool,
                 via_caixa_postal: bool = False) -> None:
        sessao.encerrar(navegador_morto=navegador_morto, via_caixa_postal=via_caixa_postal)

    def aguardar_rede(self) -> None:
        """Depois de uma queda de conexão: espera o e-CAC responder (sonda HTTP)
        e mais ESPERA_ERRO_REDE_S — a sonda volta antes do proxy do certificado."""
        _sessao.esperar_portal(self._checkpoint)
        time.sleep(ESPERA_ERRO_REDE_S)

    def abrir_mensagens_importantes(self, sessao: _sessao.Sessao, cnpj: str, *,
                                    ao_abrir) -> int:
        """Abre as mensagens importantes não lidas da empresa (regra do usuário,
        19/11/2026 — ver caixa_postal.py). `ao_abrir(isn, assunto)` a cada uma.
        Devolve quantas; levanta se sobrar alguma não lida."""
        try:
            return _caixa_postal.abrir_todas(sessao.page, cnpj, ao_abrir=ao_abrir)
        except Exception as e:
            if not navegador_fechou(e):
                self.capturar(sessao, f"caixa_postal_{cnpj}")
            raise

    # ── PER/DCOMP ────────────────────────────────────────────────────────────
    def abrir_modulo(self, sessao: _sessao.Sessao) -> None:
        navegar_modulo_perdcomp(sessao.page)

    def excluir_rascunhos(self, sessao: _sessao.Sessao) -> int:
        """Limite de rascunhos: exclui até 10 rascunhos, os da automação
        primeiro (regra do usuário, 21/11/2026 — ver rascunhos.py). Devolve quantos."""
        try:
            return _rascunhos.excluir_rascunhos(
                sessao.page, diagnostico=lambda rotulo: self.capturar(sessao, rotulo))
        except Exception as e:
            if not navegador_fechou(e):
                self.capturar(sessao, "rascunhos_erro")
            raise

    def processar_linha(self, sessao: _sessao.Sessao, linha: LinhaPerdcomp, *,
                        antes_de_enviar=None) -> Desfecho:
        """`_processar_linha`, reconhecendo o bloqueio da Caixa Postal: o aviso
        "mensagens importantes ... ainda não lidas" (só com o botão "Ir para a
        Caixa Postal") por cima do formulário — AGROFEG, 19/11/2026, travou a
        Data de Vencimento. A automação não lê mensagens: a empresa fica para
        depois. Depois do "Enviar" nada muda (envio sem confirmação continua
        quarentena)."""
        if _sessao.tem_mensagens_importantes(sessao.page, espera_ms=500):
            raise EmpresaBloqueadaNaCaixaPostal(
                "aviso de mensagens importantes não lidas na tela (a automação não abre mensagens)")
        try:
            return self._processar_linha(sessao, linha, antes_de_enviar=antes_de_enviar)
        except (EnvioSemConfirmacao, EnvioRecusadoPeloServidor, EmpresaBloqueadaNaCaixaPostal,
                SemPermissaoPerdcomp):
            raise
        except Exception as e:
            if navegador_fechou(e):
                raise
            if _sessao.tem_mensagens_importantes(sessao.page, espera_ms=500):
                raise EmpresaBloqueadaNaCaixaPostal(
                    "o aviso de mensagens importantes não lidas travou o formulário "
                    f"({type(e).__name__}) — a automação não abre mensagens") from e
            raise

    def _processar_linha(self, sessao: _sessao.Sessao, linha: LinhaPerdcomp, *,
                         antes_de_enviar=None) -> Desfecho:
        """Uma Declaração de Compensação inteira para a linha: do "Novo
        Documento" ao desfecho do envio (ver etapas_dcomp)."""
        page = sessao.page
        diagnostico = lambda rotulo: self.capturar(sessao, f"{rotulo}_linha{linha.numero_linha}")  # noqa: E731
        # Defesa extra: a empresa já foi conferida ao entrar, mas a Declaração
        # é por CNPJ — confere de novo antes de cada documento. "" (não leu) só
        # avisa: a conferência que manda é a da entrada na empresa.
        lido = _sessao.cnpj_do_perfil_ativo(page, timeout=5_000)
        if lido and lido != linha.cnpj:
            raise PerfilDivergente(f"perfil ativo {lido}, esperado {linha.cnpj}")
        if not lido:
            print("  -> [AVISO] Perfil ativo nao lido na pagina (conferido na entrada da empresa).")

        tributo = linha.tipo_credito
        for tentativa in (1, 2):
            if tentativa == 2:
                # A Receita disse que o tipo de crédito é o outro: refaz do zero
                # com PIS <-> COFINS (trocar o tipo apaga os outros campos).
                navegar_modulo_perdcomp(page)
            try:
                perdcomp = preencher_identificacao(page, tributo=tributo, perdcomp=linha.perdcomp,
                                                   diagnostico=diagnostico)
            except TelaNovoDocumentoIndisponivel:
                # "Novo Documento" não abriu a tela (diálogo inesperado do documento
                # anterior?). Recarrega o módulo e tenta uma vez.
                print("  -> [AVISO] 'Novo Documento' nao abriu a tela; recarregando o modulo...")
                diagnostico("novo_documento_nao_abriu")
                navegar_modulo_perdcomp(page)
                perdcomp = preencher_identificacao(page, tributo=tributo, perdcomp=linha.perdcomp,
                                                   diagnostico=diagnostico)
            try:
                desfecho = concluir_declaracao(
                    page, permitir_envio=PERMITIR_ACOES_REAIS_NO_ECAC, antes_de_enviar=antes_de_enviar,
                    diagnostico=diagnostico,
                    pagamento_indevido=tributo in TRIBUTOS_CREDITO_EM_ABAS,
                    conferencias_identificacao=conferencias_identificacao(
                        page, tributo=tributo, perdcomp=perdcomp))
            except PerdcompCancelado:
                # Regra do usuário (19/11/2026): AA "Perdcomp cancelado" e segue,
                # no mesmo navegador; a próxima linha recarrega o módulo.
                print(f"  -> [CANCELADO] O PER/DCOMP da linha {linha.numero_linha} esta cancelado: "
                      "vai para a AA e a execucao segue.")
                return Desfecho(True, "O documento que contém o detalhamento do crédito "
                                      "encontra-se cancelado.",
                                situacao=SITUACAO_PERDCOMP_CANCELADO, tela_conhecida=False)
            except TipoCreditoDivergente:
                if tributo in TRIBUTOS_CREDITO_EM_ABAS:
                    # Não há "outro" para tentar (a troca é só PIS <-> COFINS).
                    print(f"  -> [TRIBUTO] Tipo de credito '{TEXTO_TIPO_CREDITO[tributo]}' recusado: "
                          f"linha {linha.numero_linha} vai para a AA e a execucao segue.")
                    return Desfecho(True, f"{SITUACAO_TIPO_CREDITO_DIVERGENTE} (recusado como "
                                          f"{TEXTO_TIPO_CREDITO[tributo]})",
                                    situacao=SITUACAO_TIPO_CREDITO_DIVERGENTE,
                                    tela_conhecida=False)
                if tentativa == 2:
                    # Recusado com os DOIS tributos: é o resultado da linha (AA) —
                    # o navegador continua aberto; a próxima linha recarrega o módulo.
                    print(f"  -> [TRIBUTO] Tipo de credito recusado com PIS e com COFINS: linha "
                          f"{linha.numero_linha} vai para a AA e a execucao segue.")
                    return Desfecho(True, f"{SITUACAO_TIPO_CREDITO_DIVERGENTE} (recusado com PIS "
                                          "e com COFINS)",
                                    situacao=SITUACAO_TIPO_CREDITO_DIVERGENTE,
                                    tela_conhecida=False)
                tributo = TRIBUTO_COFINS if tributo == TRIBUTO_PIS else TRIBUTO_PIS
                print(f"  -> [TRIBUTO] A Receita indicou outro tipo de credito: refazendo a linha "
                      f"{linha.numero_linha} como {tributo} (coluna K diz {linha.tributo!r}).")
                continue
            if tributo != linha.tipo_credito:
                desfecho.tributo_corrigido = tributo
            return desfecho
        raise AssertionError("inalcancavel")

    def capturar(self, sessao: _sessao.Sessao | None, rotulo: str) -> None:
        if sessao is None:
            return
        capturar_tela(sessao.page, rotulo, self._pasta_debug)
