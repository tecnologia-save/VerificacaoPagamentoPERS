"""Verificação de Pagamento de PER/DCOMP — ponto de entrada desktop.

Suporte: Windows apenas.

Fluxo atual:
    1. Formulário: planilha de PER/DCOMPs + limite de linhas.
    2. Leitura da PRIMEIRA aba; entram as linhas com "Situação da Verificação"
       (AA) vazia, status "Análise concluída" (Z), tributo PIS/COFINS (K) e
       procurador diferente de ELIANE.
    3. Procurador (coluna B) -> .pfx em C:\\Certificados (senhas.json), tudo
       conferido ANTES de abrir o navegador.
    4. Para cada certificado, UM navegador: login (já no perfil da 1ª empresa);
       entre as empresas, troca de perfil (coluna D), sempre CONFERIDO. Empresa
       com mensagens importantes: no fim dela Caixa Postal -> Sair -> login novo.
    5. Para cada linha: módulo PER/DCOMP -> "Novo Documento" -> "Declaração de
       Compensação" -> Retificador "Não" -> Tipo de Crédito (K) -> Apelido ->
       Qualificação -> "detalhado em PER/DCOMP anterior" -> nº da coluna M ->
       "Prosseguir".
       >>> As próximas etapas ainda serão detalhadas. NADA é gravado na planilha.
    6. No fim de cada certificado: Sair com Segurança e fecha o navegador.

Igual às Protocolações: a automação roda numa thread; a janela de progresso
(Pausar/Parar) fica na thread principal; o resumo abre no fim.
"""
from __future__ import annotations

import importlib.util
import os
import platform
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

_FROZEN = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")
ROOT = Path(sys.executable).parent if _FROZEN else Path(__file__).parent

# ── Log: console + arquivo + janela ──────────────────────────────────────────
# (mesmo esquema das Protocolações: todo print vai para o console, para
# logs/exec_<data>.log e, quando a janela existe, para o painel de progresso)
_LOG_SINK = None
_LOG_FILE = None


def _registrar_log_sink(callback) -> None:
    global _LOG_SINK
    _LOG_SINK = callback


class _EspelhoStdout:
    def __init__(self, stream):
        self._stream = stream  # None no .exe windowed

    def write(self, data):
        for destino in (self._stream, _LOG_FILE):
            if destino is not None:
                try:
                    destino.write(data)
                    destino.flush()
                except Exception:  # noqa: BLE001, S110
                    pass
        if _LOG_SINK is not None:
            try:
                _LOG_SINK(data)
            except Exception:  # noqa: BLE001, S110
                pass
        return len(data)

    def flush(self):
        if self._stream is not None:
            try:
                self._stream.flush()
            except Exception:  # noqa: BLE001, S110
                pass

    def __getattr__(self, nome):
        return getattr(self._stream, nome)


def _instalar_tee_stdout() -> None:
    global _LOG_FILE
    try:
        pasta = ROOT / "logs"
        pasta.mkdir(parents=True, exist_ok=True)
        _LOG_FILE = open(
            pasta / (datetime.now().strftime("exec_%d-%m-%Y_%H-%M-%S") + f"_{os.getpid()}.log"),
            "a", encoding="utf-8", buffering=1,
        )
    except Exception:  # noqa: BLE001
        _LOG_FILE = None
    sys.stdout = _EspelhoStdout(sys.__stdout__)
    sys.stderr = _EspelhoStdout(sys.__stderr__)


_instalar_tee_stdout()

if platform.system() != "Windows":
    print(f"ERRO: este projeto so roda no Windows (SO atual: {platform.system()}).")
    sys.exit(1)

_ECAC_LOGIN_PKG = "git+https://github.com/tecnologia-save/LoginEcac-Python.git"


def _instalar_dependencias() -> None:
    """Instala o que faltar na primeira execução (mesmo padrão das Protocolações)."""
    faltando = [pacote for modulo, pacote in (
        ("openpyxl", "openpyxl>=3.1"),
        ("PIL", "Pillow"),
        ("cryptography", "cryptography"),
    ) if importlib.util.find_spec(modulo) is None]
    if faltando:
        print("PRIMEIRA EXECUCAO: instalando dependencias...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *faltando])
    if importlib.util.find_spec("ecac_login") is None:
        print("  -> Instalando ecac_login (ResolvedorCaptcha vem junto)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", _ECAC_LOGIN_PKG])
        os.execv(sys.executable, [sys.executable, *sys.argv])


if not _FROZEN:
    _instalar_dependencias()

from ecac_login import fazer_login  # noqa: E402

try:  # perfil do Chrome sempre em disco local (Drive/rede travam o Chrome)
    from ecac_login import dir_perfil_chrome as _dir_perfil_chrome
except ImportError:  # ecac_login antigo
    _dir_perfil_chrome = None
import inspect  # noqa: E402

PERFIL_CHROME = (
    _dir_perfil_chrome(ROOT)
    if _dir_perfil_chrome is not None and "perfil_dir" in inspect.signature(fazer_login).parameters
    else None
)

sys.path.insert(0, str(ROOT))
from log_manager import registrar_erro  # noqa: E402
from progresso import AutomacaoInterrompida, JanelaProgresso  # noqa: E402
from ui_formulario_inicial import DadosIniciais, coletar_dados_iniciais  # noqa: E402
from ui_resumo_final import mostrar_resumo  # noqa: E402
from VerificacaoPagamento.certificados import (  # noqa: E402
    CertificadoIndisponivel,
    ler_senhas,
    listar_pfx,
)
from VerificacaoPagamento.config import (  # noqa: E402
    PASTA_CERTIFICADOS,
    PERMITIR_ACOES_REAIS_NO_ECAC,
    SITUACAO_VERIFICAR,
)
from VerificacaoPagamento.desfechos import ExecucaoInterrompida  # noqa: E402
from VerificacaoPagamento.execucao import ResultadoLinha, executar, preparar_lote  # noqa: E402
from VerificacaoPagamento.planilha import ler_planilha  # noqa: E402
from VerificacaoPagamento.portal import PortalReal  # noqa: E402
from VerificacaoPagamento.registro import RegistroResultados  # noqa: E402

PASTA_DEBUG = ROOT / "debug_telas"

# Checkpoint de pausa/parada (registrado pela janela de progresso).
_PAUSA_GATE = None

# Duas sessões do e-CAC ao mesmo tempo, divididas por certificado (pedido do
# usuário, 18/11/2026). Sessão 1 = perfil do Chrome e diário de sempre.
_SESSAO = 1
_CERTIFICADOS: list[str] = []
_EXCETO_CERTIFICADOS: list[str] = []


def _perfil_da_sessao():
    if PERFIL_CHROME is None or _SESSAO == 1:
        return PERFIL_CHROME
    return Path(PERFIL_CHROME).with_name(f"{Path(PERFIL_CHROME).name}_sessao{_SESSAO}")


def _pausa() -> None:
    if _PAUSA_GATE is not None:
        _PAUSA_GATE()


def iniciar_automacao(dados: DadosIniciais, progresso=None, navegador_aberto: bool = False) -> dict:
    """Roda na thread da automação. Nunca abre janela nem chama sys.exit:
    qualquer falha vira `motivo_parada` no payload do resumo."""
    total_fases = 4
    feitas = [0]

    def _fase(nome: str, ini: float, fim: float) -> None:
        feitas[0] += 1
        print(f"\n===== ETAPA {feitas[0]}/{total_fases}: {nome} =====")
        if progresso is not None:
            progresso.fase(nome, ini, fim)

    resultados: list[ResultadoLinha] = []
    avisos: list[str] = []
    nome_planilha = Path(dados.caminho_planilha).name

    def _resumo(motivo: str = "") -> dict:
        return {
            "empresa": "Verificação de Pagamento",
            "cnpj": nome_planilha,
            "linhas": [r.como_resumo() for r in resultados],
            "motivo_parada": motivo,
            "modo_teste": not PERMITIR_ACOES_REAIS_NO_ECAC,
            "avisos": avisos,
            "pasta_destino": None,
        }

    print("=" * 60)
    print("[MODO SEGURO] PERMITIR_ACOES_REAIS_NO_ECAC=False" if not PERMITIR_ACOES_REAIS_NO_ECAC
          else "[EXECUCAO REAL] PERMITIR_ACOES_REAIS_NO_ECAC=True")
    print("=" * 60)
    print(f"  -> Planilha        : {dados.caminho_planilha}")
    print(f"  -> Limite empresas : {dados.limite_empresas or 'todas'}")
    print(f"  -> Limite de linhas: {dados.limite_linhas or 'todas'}")
    if _SESSAO != 1 or _CERTIFICADOS or _EXCETO_CERTIFICADOS:
        print(f"  -> Sessao          : {_SESSAO}")
        print(f"  -> Certificados    : {', '.join(_CERTIFICADOS) or 'todos'}"
              + (f" (exceto {', '.join(_EXCETO_CERTIFICADOS)})" if _EXCETO_CERTIFICADOS else ""))
    if not (ROOT / ".env").is_file():
        avisos.append("Não há .env na pasta do robô: sem GEMINI_API_KEY o captcha do gov.br "
                      "não é resolvido automaticamente.")
        print("  -> [AVISO] .env ausente — o captcha pode nao ser resolvido.")

    _fase("Lendo a planilha", 0, 4)
    try:
        planilha = ler_planilha(dados.caminho_planilha)
    except Exception as e:  # noqa: BLE001
        print(f"[ERRO] Falha ao ler a planilha: {type(e).__name__}: {e}")
        return _resumo(f"falha ao ler a planilha — {e}")
    print(f"  -> Aba             : {planilha.nome_aba}")
    print(f"  -> Linhas na aba   : {len(planilha.linhas)}")

    # Resultados: diário imediato + coluna AA em lote. Só em execução real —
    # no modo seguro nada é gravado. A reconciliação vem ANTES do lote: linha
    # com resultado no diário (inclusive tentativa de envio sem desfecho) não
    # volta a ser processada, mesmo que a AA não tenha sido gravada.
    registro = None
    if PERMITIR_ACOES_REAIS_NO_ECAC:
        registro = RegistroResultados(dados.caminho_planilha, ROOT / "resultados", ROOT / "backups",
                                      em_segundo_plano=True, sessao=_SESSAO)
        reconciliadas = registro.reconciliar(planilha)
        if reconciliadas:
            print(f"  -> {reconciliadas} linha(s) com resultado ja conhecido (diario ou PER/DCOMP "
                  "repetido) e AA vazia: entram na planilha agora e ficam fora do lote.")
            registro.salvar()
    print(f"  -> Linhas pendentes na planilha: {len(planilha.pendentes)}")

    _fase("Conferindo os certificados", 4, 8)
    try:
        senhas = ler_senhas()
    except CertificadoIndisponivel as e:
        print(f"[ERRO] {e}")
        return _resumo(str(e))
    somente_certificado = None
    if navegador_aberto:
        import json
        estado = ROOT / "navegador_aberto.json"
        if not estado.is_file():
            print("[ERRO] --navegador-aberto: nenhum navegador aberto (rode manter_navegador.py).")
            return _resumo("nenhum navegador aberto — rode manter_navegador.py antes.")
        somente_certificado = json.loads(estado.read_text(encoding="utf-8"))["certificado"]
    lote = preparar_lote(planilha, dados.limite_linhas, listar_pfx(PASTA_CERTIFICADOS), senhas,
                         limite_empresas=dados.limite_empresas,
                         somente_certificado=somente_certificado,
                         certificados_incluidos=_CERTIFICADOS,
                         certificados_excluidos=_EXCETO_CERTIFICADOS)
    avisos.extend(lote.avisos)
    for info in lote.informacoes:
        print(f"  -> {info}")
    for aviso in lote.avisos:
        print(f"  -> [AVISO] {aviso}")
    print(f"  -> Linhas no lote  : {lote.total_linhas}")
    for grupo in lote.grupos:
        print(f"     {grupo.certificado}: {len(grupo.empresas)} empresa(s), "
              f"{grupo.total_linhas} linha(s)")
        if dados.limite_empresas:
            for empresa in grupo.empresas:
                print(f"       - {empresa.empresa.strip()} ({empresa.cnpj}): linhas "
                      + ", ".join(str(ln.numero_linha) for ln in empresa.linhas))
    if not lote.grupos:
        return _resumo("nenhuma linha pendente pôde entrar no lote (ver avisos)."
                       if lote.linhas_fora else "")

    _fase("Processando as linhas", 8, 98)
    portal = PortalReal(
        project_dir=ROOT, perfil_dir=_perfil_da_sessao(), pasta_debug=PASTA_DEBUG,
        checkpoint=_pausa,
        cancelado=lambda: bool(progresso is not None and progresso.parada_solicitada),
        navegador_aberto=navegador_aberto,
    )
    motivo = ""
    try:
        executar(lote, portal, checkpoint=_pausa, registro=registro, resultados=resultados)
    except AutomacaoInterrompida:
        motivo = "parada solicitada pelo usuário."
        print("\n[PARADA] Execucao interrompida pelo usuario.")
    except ExecucaoInterrompida as e:
        motivo = str(e)
        print(f"\n[PARADA] {e}")
    except Exception as e:  # noqa: BLE001
        registrar_erro(f"VERIFICACAO: erro inesperado: {type(e).__name__}: {e}")
        motivo = f"erro inesperado — {type(e).__name__}: {e}"

    _fase("Encerrando", 98, 100)
    if registro is not None:
        # PER/DCOMPs repetidos herdam o resultado da linha que foi ao e-CAC.
        herdadas = registro.reconciliar(planilha)
        if herdadas:
            print(f"  -> {herdadas} linha(s) com PER/DCOMP repetido receberam o mesmo resultado.")
        if not registro.fechar():
            avisos.append(
                f"A coluna AA da planilha NÃO pôde ser gravada ({registro.ultima_falha}) — ela "
                "estava aberta no Excel? Os resultados estão salvos no diário "
                f"{registro.diario} e entram na planilha na próxima execução."
            )
        quarentena = [r.numero_linha for r in resultados
                      if r.detalhe.startswith(SITUACAO_VERIFICAR)]
        if quarentena:
            avisos.append(
                f"{len(quarentena)} linha(s) ficaram com o ENVIO SEM CONFIRMAÇÃO (linhas "
                f"{', '.join(map(str, quarentena))}) e foram marcadas '{SITUACAO_VERIFICAR}'. "
                "Confira no e-CAC se a Declaração de Compensação foi transmitida antes de mexer "
                "nessas linhas: nenhuma execução vai reenviá-las."
            )
    ok = sum(1 for r in resultados if r.ok)
    print("\n" + "=" * 60)
    print("EXECUCAO FINALIZADA")
    print(f"  -> Linhas processadas : {len(resultados)}")
    print(f"  -> Com sucesso        : {ok}")
    print(f"  -> Com falha          : {len(resultados) - ok}")
    print("=" * 60)
    return _resumo(motivo)


def _argumentos():
    """Sem argumentos: o formulário. Com --planilha: roda direto, sem janelas
    (o log vai para o console e para logs/), e imprime o resumo."""
    import argparse

    parser = argparse.ArgumentParser(description="Verificação de Pagamento PER/DCOMP")
    parser.add_argument("--planilha", help="planilha de PER/DCOMPs (pula o formulário)")
    parser.add_argument("--limite-empresas", type=int, default=None)
    parser.add_argument("--limite-linhas", type=int, default=None)
    parser.add_argument("--navegador-aberto", action="store_true",
                        help="usa o Chrome já logado de manter_navegador.py (sem login, sem fechar)")
    parser.add_argument("--sessao", type=int, default=1,
                        help="nº da sessão (2, 3...): perfil do Chrome e diário próprios")
    parser.add_argument("--certificados", default="",
                        help="só estes certificados, separados por vírgula")
    parser.add_argument("--exceto-certificados", default="",
                        help="todos os certificados menos estes, separados por vírgula")
    parser.add_argument("--modo-seguro", action="store_true",
                        help="teste: vai até 'apto para envio', não clica em Enviar, não grava nada")
    parser.add_argument("--ignorar-pausa-noturna", action="store_true",
                        help="teste: não pausa das 0h58 às 3h01 (use só com --modo-seguro)")
    return parser.parse_args()


MAX_PASSES = 10
PAUSA_ENTRE_PASSES_S = 60


def _rodar_sem_janela(dados: DadosIniciais, navegador_aberto: bool = False) -> None:
    """Roda em PASSES até não sobrar linha (pedido do usuário, 18/11/2026:
    "rodando 24 h, tentando até conseguir, sem parar"). Cada passe relê a
    planilha: só voltam as linhas com a AA vazia — as que falharam. Para quando
    tudo deu certo, quando um passe inteiro não resolve nenhuma linha (o que
    sobrou não é instabilidade), ou no teto de MAX_PASSES."""
    for passe in range(1, MAX_PASSES + 1):
        print("\n" + "#" * 60)
        print(f"PASSE {passe}/{MAX_PASSES}")
        print("#" * 60)
        resultado = iniciar_automacao(dados, progresso=None, navegador_aberto=navegador_aberto)
        linhas = resultado.get("linhas", [])
        ok = sum(1 for item in linhas if item["ok"])
        falhas = [item for item in linhas if not item["ok"]]
        print()
        print("=" * 60)
        print(f"RESUMO DO PASSE {passe}: {len(linhas)} linha(s), {ok} ok, {len(falhas)} com falha")
        for item in falhas[:50]:
            print(f"  [FALHA] {item['rotulo']} — {item['detalhe']}")
        if len(falhas) > 50:
            print(f"  ... e mais {len(falhas) - 50} falha(s) (ver o log)")
        if resultado.get("motivo_parada"):
            print(f"  Interrompida: {resultado['motivo_parada']}")
        for aviso in resultado.get("avisos", []):
            print(f"  [AVISO] {aviso}")
        print("=" * 60)
        if not falhas:
            print("Todas as linhas resolvidas.")
            return
        if ok == 0:
            print("Nenhuma linha resolvida neste passe: o que sobrou nao e instabilidade. Parando.")
            return
        print(f"{len(falhas)} linha(s) com falha voltam no proximo passe (em {PAUSA_ENTRE_PASSES_S}s).")
        time.sleep(PAUSA_ENTRE_PASSES_S)


def main() -> None:
    global _PAUSA_GATE
    global _SESSAO, _CERTIFICADOS, _EXCETO_CERTIFICADOS, PERMITIR_ACOES_REAIS_NO_ECAC
    argumentos = _argumentos()
    _SESSAO = max(1, argumentos.sessao)
    _CERTIFICADOS = [n.strip() for n in argumentos.certificados.split(",") if n.strip()]
    _EXCETO_CERTIFICADOS = [n.strip() for n in argumentos.exceto_certificados.split(",") if n.strip()]
    if argumentos.ignorar_pausa_noturna and not argumentos.modo_seguro:
        print("ERRO: --ignorar-pausa-noturna so pode ser usado com --modo-seguro "
              "(das 1h as 3h o Receitanet nao transmite).")
        return
    if argumentos.modo_seguro:
        # Teste: vai até "apto para envio" e NÃO clica em Enviar; nada é gravado.
        import VerificacaoPagamento.config as _config
        import VerificacaoPagamento.portal as _portal
        PERMITIR_ACOES_REAIS_NO_ECAC = False
        _config.PERMITIR_ACOES_REAIS_NO_ECAC = False
        _portal.PERMITIR_ACOES_REAIS_NO_ECAC = False
    if argumentos.ignorar_pausa_noturna:
        # Só para teste (com --modo-seguro): o Receitanet não transmite das 1h às 3h.
        import VerificacaoPagamento.execucao as _execucao
        _execucao.na_janela_receitanet = lambda agora: False
    if argumentos.planilha:
        _rodar_sem_janela(DadosIniciais(
            caminho_planilha=argumentos.planilha, limite_linhas=argumentos.limite_linhas,
            limite_empresas=argumentos.limite_empresas),
            navegador_aberto=argumentos.navegador_aberto)
        return

    dados = coletar_dados_iniciais()
    if dados is None:
        print("  -> Cancelado.")
        return

    janela = JanelaProgresso(subtitulo=Path(dados.caminho_planilha).name)
    _registrar_log_sink(janela.log)
    _PAUSA_GATE = janela.aguardar_se_pausado
    resultado: dict = {}

    def _rodar():
        try:
            resultado.update(iniciar_automacao(dados, progresso=janela) or {})
        except AutomacaoInterrompida:
            resultado.update({"motivo_parada": "parada solicitada pelo usuário."})
        except BaseException as e:  # noqa: BLE001 — fronteira da thread: tudo vira motivo no resumo
            registrar_erro(f"VERIFICACAO: erro fatal: {type(e).__name__}: {e}")
            resultado.update({"motivo_parada": f"erro inesperado — {type(e).__name__}: {e}"})
        finally:
            janela.finalizar()

    threading.Thread(target=_rodar, daemon=True).start()
    janela.mainloop()
    _registrar_log_sink(None)
    time.sleep(0.1)

    if resultado:
        mostrar_resumo(
            empresa=resultado.get("empresa", "Verificação de Pagamento"),
            cnpj=resultado.get("cnpj", ""),
            linhas=resultado.get("linhas", []),
            pasta_destino=resultado.get("pasta_destino"),
            motivo_parada=resultado.get("motivo_parada", ""),
            modo_teste=resultado.get("modo_teste", True),
            avisos=resultado.get("avisos", []),
        )


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:  # noqa: BLE001 — topo do .exe windowed: sem isto o erro some
        registrar_erro(f"VERIFICACAO: erro fatal na inicializacao: {type(e).__name__}: {e}")
        try:
            import tkinter.messagebox as _mb
            _mb.showerror("Erro", f"A automação encontrou um erro e será encerrada:\n\n"
                                  f"{type(e).__name__}: {e}")
        except Exception:  # noqa: BLE001, S110
            pass
        sys.exit(1)
