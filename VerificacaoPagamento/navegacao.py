"""Navegação da página logada do e-CAC até o módulo PER/DCOMP.

Porte direto de `navegacao.py` das Protocolações (mesmo app Angular): URL fixa
do módulo e espera o app dentro do iframe terminar de carregar (nav lateral
visível). Recarrega até `tentativas` vezes — o servidor da Receita às vezes
devolve 500 nos chunks JS do Angular e o app não termina de subir.
"""
import time

from .config import FRAME_PERDCOMP, PERDCOMP_URL, SELETOR_NAV_NOVO_DOCUMENTO
from .desfechos import EmpresaBloqueadaNaCaixaPostal, SemPermissaoPerdcomp
from .formulario_perdcomp import navegador_fechou


def caixa_postal_no_lugar_do_modulo(page) -> bool:
    """O app aberto no iframe é a Caixa Postal (bloqueio por mensagem
    importante não lida), e não o PER/DCOMP."""
    try:
        src = page.locator(FRAME_PERDCOMP).first.get_attribute("src", timeout=3_000) or ""
    except Exception as e:
        if navegador_fechou(e):
            raise
        src = ""
    return "caixapostal" in src.lower() or "id=00006" in (page.url or "")


def _conferir_bloqueio(page) -> None:
    if caixa_postal_no_lugar_do_modulo(page):
        raise EmpresaBloqueadaNaCaixaPostal(
            "o e-CAC abriu a Caixa Postal no lugar do PER/DCOMP (mensagem importante não lida — "
            "a automação não abre mensagens)")


TEXTO_SEM_PERMISSAO = "não possui permissão ou a execução exige acesso com certificado digital"


def sem_permissao(page) -> bool:
    """O e-CAC mostrou "Seu perfil não possui permissão ou a execução exige
    acesso com certificado digital" (na página ou em algum quadro)."""
    for quadro in page.frames:
        try:
            texto = quadro.locator("body").first.inner_text(timeout=2_000)
        except Exception as e:
            if navegador_fechou(e):
                raise
            continue
        if TEXTO_SEM_PERMISSAO in " ".join(texto.split()).casefold():
            return True
    return False


def _conferir_permissao(page) -> None:
    if sem_permissao(page):
        raise SemPermissaoPerdcomp("o perfil não possui permissão para o PER/DCOMP (procuração "
                                   "sem esse poder)")


class PerdcompWebIndisponivel(Exception):
    """O PERDCOMP-WEB não terminou de carregar após várias tentativas."""


def navegar_modulo_perdcomp(page, timeout: int = 30_000, timeout_app: int = 120_000,
                            tentativas: int = 3) -> None:
    page.goto(PERDCOMP_URL, wait_until="domcontentloaded", timeout=timeout)
    _conferir_bloqueio(page)
    page.wait_for_timeout(1_500)
    _conferir_permissao(page)

    for tentativa in range(1, tentativas + 1):
        try:
            page.frame_locator(FRAME_PERDCOMP).locator(SELETOR_NAV_NOVO_DOCUMENTO).first.wait_for(
                state="visible", timeout=timeout_app
            )
            return
        except Exception as e:
            if navegador_fechou(e):
                raise
            _conferir_bloqueio(page)
            _conferir_permissao(page)
            if tentativa == tentativas:
                raise PerdcompWebIndisponivel(
                    f"PERDCOMP-WEB não carregou após {tentativas} tentativas — provável "
                    "instabilidade no servidor da Receita."
                ) from None
            print(f"  -> [AVISO] PERDCOMP-WEB nao carregou na tentativa {tentativa}/{tentativas}. "
                  "Recarregando...")
            time.sleep(3)
            page.reload(wait_until="domcontentloaded", timeout=timeout)
