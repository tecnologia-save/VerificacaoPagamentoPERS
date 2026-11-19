"""Sessão do e-CAC: login com o .pfx, troca de empresa e saída.

Um login por CERTIFICADO; entre as empresas do mesmo certificado só se troca
o perfil (`garantir_acesso_ecac`), sem fechar o navegador — mesmo esquema do
VerificaMensagensPagamento desktop. Trocar de certificado = sair com segurança,
fechar, e logar de novo com o outro .pfx.

Sair SEMPRE com "Sair com Segurança" antes de fechar: o certificado tem número
limitado de perfis logados ao mesmo tempo e fechar o Chrome não libera a vaga
do lado da Receita (`ecac_login.encerrar_sessao` faz as duas coisas).

MENSAGENS IMPORTANTES: desde 19/11/2026 (regra do usuário) a automação abre
as importantes não lidas na Caixa Postal (caixa_postal.py) e segue com a
empresa. Se não conseguir, vale o procedimento anterior: depois da empresa NÃO
dá para trocar o perfil, então Caixa Postal -> Sair com Segurança -> fecha ->
login novo para a próxima.

ATENÇÃO — por que o perfil ativo é CONFERIDO: o `ecac_login` procura o popup
ANTES de trocar o perfil e, se o encontra, clica "Ir para a Caixa Postal" e
devolve sucesso SEM ter trocado. Sem conferir, a Declaração sairia no CNPJ
da empresa anterior (ou do titular).
"""
from __future__ import annotations

import inspect
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .certificados import Certificado
from .config import CAIXA_POSTAL_URL
from .formulario_perdcomp import navegador_fechou

# Esperas do gov.br. Com teto: a planilha tem centenas de empresas, e esperar
# sem limite num bloqueio prenderia a execução inteira.
ESPERA_ACESSO_BLOQUEADO_S = 15
ESPERA_DISPOSITIVOS_S = 30
MAX_ESPERAS_GOVBR = 10
ESPERA_ENTRE_TENTATIVAS_S = 20


class LoginNaoConcluido(Exception):
    """O login com este certificado não foi concluído (não é culpa da empresa)."""


class PerfilRecusado(Exception):
    """O e-CAC recusou representar o CNPJ (procuração expirada/inexistente,
    acesso automatizado...). Vale para a EMPRESA, não para o certificado."""


@dataclass
class Sessao:
    playwright: object
    contexto: object
    page: object
    certificado: str
    cnpj_ativo: str
    # A empresa ativa tem "mensagens importantes" na Caixa Postal: o popup não
    # impede o PER/DCOMP (pelo link), mas TRAVA a troca de perfil. No fim da
    # empresa, a sessão sai pela Caixa Postal e o próximo CNPJ faz login novo.
    mensagens_importantes: bool = False
    # Sessão de um "navegador aberto" (ver `conectar_navegador_aberto`): quem
    # é dono do Chrome é outro processo. Encerrar = só desconectar — NÃO sai do
    # e-CAC nem fecha, para o login continuar valendo para a próxima execução.
    reaproveitada: bool = False

    def encerrar(self, *, navegador_morto: bool = False, via_caixa_postal: bool = False) -> None:
        """Sai com segurança e fecha. Idempotente; nunca levanta.

        `via_caixa_postal`: passa pela Caixa Postal antes de sair (empresa com
        mensagens importantes — procedimento definido pelo usuário, 18/11/2026)."""
        from ecac_login import encerrar_sessao

        if self.reaproveitada:
            try:
                self.playwright.stop()  # só a conexão CDP; o Chrome é do outro processo
            except Exception:  # noqa: BLE001, S110
                pass
            print("  -> Desconectado do navegador aberto (login mantido).")
            return
        if via_caixa_postal and not navegador_morto:
            ir_para_caixa_postal(self.page)
        try:
            encerrar_sessao(self.playwright, self.contexto, sair=not navegador_morto)
            print("  -> Navegador fechado.")
        except Exception as e:  # noqa: BLE001 — encerrar nunca derruba quem chamou
            print(f"  -> [AVISO] Falha ao encerrar a sessao: {type(e).__name__}: {e}")


# ── Perfil ativo e mensagens importantes (página-shell do e-CAC) ─────────────
#
# O shell do e-CAC — inclusive a página que hospeda o PERDCOMP-WEB — mostra o
# perfil ativo (HTML capturado na Restituição):
#   <div id="informacao-perfil">
#     <div><span>Titular (Acesso GOV.BR por Certificado): 24.245.826/0001-89 - SAVE ...</span></div>
#     <div><span>Procurador de: 09.435.440/0001-46 - TERRA NOVA ...</span></div>
#   </div>
SELETOR_INFORMACAO_PERFIL = "#informacao-perfil"
# Popup de "mensagens importantes" (mesmo id usado pelo ecac_login e pelo
# VerificaMensagensPagamento).
SELETOR_POPUP_MENSAGENS = "#dialog-bloqueio-ativo-caixapostal"
ESPERA_POPUP_MENSAGENS_MS = 5_000

_RX_CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")


def cnpj_do_texto_de_perfil(texto: str) -> str:
    """O CNPJ representado, a partir do texto de #informacao-perfil.

    Com "Procurador de: X" é X; sem procuração (o titular atuando por si), é o
    do titular. "" se não houver CNPJ legível."""
    texto = texto or ""
    marcador = texto.casefold().find("procurador de")
    trecho = texto[marcador:] if marcador >= 0 else texto
    achado = _RX_CNPJ.search(trecho)
    return re.sub(r"\D", "", achado.group(0)) if achado else ""


def cnpj_do_perfil_ativo(page, timeout: int = 15_000) -> str:
    """O CNPJ do perfil ativo, lido da página-shell do e-CAC ("" se não leu)."""
    try:
        alvo = page.locator(SELETOR_INFORMACAO_PERFIL).first
        alvo.wait_for(state="attached", timeout=timeout)
        return cnpj_do_texto_de_perfil(alvo.inner_text(timeout=timeout))
    except Exception as e:
        if navegador_fechou(e):
            raise
        return ""


def tem_mensagens_importantes(page, espera_ms: int = ESPERA_POPUP_MENSAGENS_MS) -> bool:
    """O popup de "mensagens importantes" está (ou aparece em `espera_ms`) na tela?"""
    try:
        page.locator(SELETOR_POPUP_MENSAGENS).first.wait_for(state="visible", timeout=espera_ms)
        return True
    except Exception as e:
        if navegador_fechou(e):
            raise
        return False


def ir_para_caixa_postal(page) -> None:
    """Abre a Caixa Postal — pelo botão do popup, se estiver na tela; senão pela
    URL. Best-effort: a saída com segurança vem logo depois de qualquer jeito."""
    try:
        botao = page.get_by_role("button", name="Ir para a Caixa Postal").first
        if botao.is_visible():
            botao.click(timeout=10_000)
        else:
            page.goto(CAIXA_POSTAL_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_load_state("domcontentloaded", timeout=30_000)
        print("  -> Caixa Postal aberta.")
    except Exception as e:  # noqa: BLE001 — segue para o "Sair com Segurança"
        print(f"  -> [AVISO] Nao foi possivel abrir a Caixa Postal ({type(e).__name__}).")


CDP_NAVEGADOR_ABERTO = "http://localhost:9222"


def conectar_navegador_aberto(cdp_url: str = CDP_NAVEGADOR_ABERTO) -> Sessao | None:
    """Conecta ao Chrome já logado no e-CAC (mantido por `manter_navegador.py`),
    pela porta de depuração que o `ecac_login` abre. None se não houver um.

    Pedido do usuário (18/11/2026): não perder o login entre as execuções —
    cada login novo gasta captcha e uma vaga de dispositivo do certificado."""
    from patchright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(cdp_url, timeout=10_000)
    except Exception as e:  # noqa: BLE001 — sem navegador aberto: None
        print(f"[navegador aberto] Nenhum Chrome em {cdp_url} ({type(e).__name__}).")
        playwright.stop()
        return None
    paginas = [pg for contexto in browser.contexts for pg in contexto.pages
               if "receita.fazenda.gov.br" in (pg.url or "")]
    if not paginas:
        print("[navegador aberto] O Chrome aberto nao esta no e-CAC.")
        playwright.stop()
        return None
    page = paginas[0]
    page.bring_to_front()
    print(f"[navegador aberto] Conectado (perfil ativo: {cnpj_do_perfil_ativo(page) or '?'}).")
    return Sessao(playwright=playwright, contexto=None, page=page, certificado="(navegador aberto)",
                  cnpj_ativo=cnpj_do_perfil_ativo(page), reaproveitada=True)


def _aceita(funcao, parametro: str) -> bool:
    try:
        return parametro in inspect.signature(funcao).parameters
    except (TypeError, ValueError):
        return False


def _dormir(segundos: float, checkpoint) -> None:
    """Dorme de segundo em segundo, passando pelo checkpoint de pausa/parada."""
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        if checkpoint is not None:
            checkpoint()
        time.sleep(min(1.0, max(0.0, fim - time.monotonic())))


URL_SONDA_PORTAL = "https://cav.receita.fazenda.gov.br/ecac/"
USER_AGENT_SONDA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
ESPERA_PORTAL_S = 60
# Teto da espera pelo portal: depois disso, o login conta como não concluído.
MAX_ESPERA_PORTAL_S = 6 * 3600


def portal_responde(timeout_s: float = 15) -> bool:
    """O e-CAC responde a um pedido HTTPS simples? Sem navegador e sem login.

    Medido em 18/11/2026 com o e-CAC fora do ar: o pedido estoura o tempo
    (fora do Chrome também), e o Chrome mostra ERR_BLOCKED_BY_CLIENT no http e
    ERR_CONNECTION_TIMED_OUT no https — não é bloqueio local, é o portal.

    O PEDIDO SE IDENTIFICA COMO NAVEGADOR: o e-CAC derruba (connection reset)
    conexões sem User-Agent de navegador — sem isso, com o portal no ar, a
    sonda dizia "fora do ar" (medido no mesmo dia: sem UA = reset em 0,1 s; com
    UA = 200 em 0,3 s). E um reset É resposta do servidor: o portal está de pé.
    Só tempo esgotado, conexão recusada ou DNS contam como fora do ar."""
    import ssl
    import urllib.error
    import urllib.request

    pedido = urllib.request.Request(URL_SONDA_PORTAL, headers={"User-Agent": USER_AGENT_SONDA})
    try:
        with urllib.request.urlopen(  # noqa: S310 — URL fixa do e-CAC
                pedido, timeout=timeout_s,
                context=ssl._create_unverified_context()) as resposta:  # noqa: S323
            return resposta.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500  # respondeu (ex.: 403/404): o portal está de pé
    except ConnectionResetError:
        return True  # o servidor respondeu derrubando: está no ar
    except urllib.error.URLError as e:
        return isinstance(e.reason, ConnectionResetError)
    except Exception:  # noqa: BLE001 — timeout, conexão recusada, DNS: fora do ar
        return False


def esperar_portal(checkpoint=None, *, espera_s: float = ESPERA_PORTAL_S,
                   maximo_s: float = MAX_ESPERA_PORTAL_S, sonda=portal_responde) -> None:
    """Bloqueia até o e-CAC responder. Levanta LoginNaoConcluido após `maximo_s`."""
    if sonda():
        return
    inicio = time.monotonic()
    print(f"[portal] e-CAC fora do ar (nao responde). Nova verificacao a cada {espera_s:.0f}s...")
    while True:
        _dormir(espera_s, checkpoint)
        aguardando = time.monotonic() - inicio
        if sonda():
            print(f"[portal] e-CAC voltou depois de {aguardando / 60:.0f} min. Seguindo com o login.")
            return
        if aguardando >= maximo_s:
            raise LoginNaoConcluido(f"e-CAC fora do ar por mais de {maximo_s / 3600:.0f}h")
        print(f"[portal] e-CAC ainda fora do ar ({aguardando / 60:.0f} min aguardando)...")


def abrir_sessao(certificado: Certificado, cnpj: str, *, project_dir: Path,
                 perfil_dir: Path | None = None, tentativas: int = 2,
                 checkpoint=None, cancelado=None) -> Sessao:
    """Login no e-CAC com o .pfx, já no perfil do `cnpj`.

    Levanta PerfilRecusado quando o login chegou até a troca de perfil e o
    e-CAC recusou ESTE CNPJ (as outras empresas do certificado seguem); e
    LoginNaoConcluido quando o problema é o caminho até o e-CAC.
    """
    from ecac_login import (
        AcessoBloqueado,
        DispositivosMaximo,
        PortalIndisponivel,
        fazer_login,
        tentou_trocar_perfil,
        ultima_recusa_de_perfil,
    )

    argumentos = {
        "cnpj": cnpj,
        "project_dir": str(project_dir),
        # Com .pfx não há policy do Windows; True evita o fallback que procura
        # a janela nativa de escolha de certificado (que não aparece neste modo).
        "policy_ok": True,
        "cert_pfx_path": str(certificado.caminho),
        "cert_pfx_passphrase": certificado.senha,
    }
    if perfil_dir is not None and _aceita(fazer_login, "perfil_dir"):
        argumentos["perfil_dir"] = str(perfil_dir)
    if cancelado is not None and _aceita(fazer_login, "cancelado"):
        argumentos["cancelado"] = cancelado

    falhas = 0
    esperas_govbr = 0
    ultimo_erro = ""
    while True:
        if checkpoint is not None:
            checkpoint()
        # e-CAC fora do ar: espera voltar SEM abrir o Chrome (cada login gasta
        # captcha e uma vaga de dispositivo do certificado).
        esperar_portal(checkpoint)
        ultimo_erro = ""
        try:
            resultado = fazer_login(**argumentos)
        except PortalIndisponivel:
            # Caiu no meio do login: não é falha do certificado nem da empresa.
            print("[portal] O e-CAC parou de responder durante o login; aguardando voltar...")
            continue
        except AcessoBloqueado:
            esperas_govbr += 1
            if esperas_govbr > MAX_ESPERAS_GOVBR:
                raise LoginNaoConcluido("acesso bloqueado pelo gov.br repetidamente") from None
            print(f"[login] Acesso bloqueado. Aguardando {ESPERA_ACESSO_BLOQUEADO_S}s "
                  f"({esperas_govbr}/{MAX_ESPERAS_GOVBR})...")
            _dormir(ESPERA_ACESSO_BLOQUEADO_S, checkpoint)
            continue
        except DispositivosMaximo:
            esperas_govbr += 1
            if esperas_govbr > MAX_ESPERAS_GOVBR:
                raise LoginNaoConcluido("limite de dispositivos do certificado atingido") from None
            print(f"[login] Numero maximo de dispositivos atingido. Aguardando "
                  f"{ESPERA_DISPOSITIVOS_S}s ({esperas_govbr}/{MAX_ESPERAS_GOVBR})...")
            _dormir(ESPERA_DISPOSITIVOS_S, checkpoint)
            continue
        except Exception as e:
            if type(e).__name__ == "LoginCancelado":
                raise
            resultado = None
            ultimo_erro = f"{type(e).__name__}: {e}"
            print(f"[login] Erro: {ultimo_erro}")

        if resultado is not None:
            p, contexto, page = resultado
            return Sessao(playwright=p, contexto=contexto, page=page,
                          certificado=certificado.nome, cnpj_ativo=cnpj)

        # O login chegou à troca de perfil e o e-CAC recusou ESTE CNPJ: não
        # adianta repetir, e as outras empresas do certificado ainda podem entrar.
        if not ultimo_erro and tentou_trocar_perfil():
            raise PerfilRecusado(ultima_recusa_de_perfil() or "o e-CAC não aceitou o perfil")

        falhas += 1
        if falhas >= tentativas:
            raise LoginNaoConcluido(ultimo_erro or "login não concluído")
        print(f"[login] Login nao concluido (tentativa {falhas}/{tentativas}). "
              f"Tentando de novo em {ESPERA_ENTRE_TENTATIVAS_S}s...")
        _dormir(ESPERA_ENTRE_TENTATIVAS_S, checkpoint)


def trocar_empresa(sessao: Sessao, cnpj: str) -> None:
    """Troca o perfil para `cnpj` NA SESSÃO ABERTA (sem fechar o navegador).

    Levanta PerfilRecusado se o e-CAC recusar; deixa subir o erro de navegador
    fechado (quem chama reabre a sessão)."""
    from ecac_login import (
        AcessoBloqueado,
        PortalIndisponivel,
        garantir_acesso_ecac,
        ultima_recusa_de_perfil,
    )

    if sessao.cnpj_ativo == cnpj:
        return
    print(f"  [perfil] Alterando perfil para o CNPJ {cnpj}...")
    try:
        ok = garantir_acesso_ecac(sessao.page, cnpj, policy_ok=True)
    except AcessoBloqueado:
        raise PerfilRecusado("acesso bloqueado pelo gov.br") from None
    except Exception as e:
        if navegador_fechou(e):
            raise
        if isinstance(e, PortalIndisponivel) or "net::ERR_" in str(e):
            # REDE, não a empresa (19/11/2026: ERR_BLOCKED_BY_CLIENT derrubou 192
            # linhas como "perfil recusado"). Sobe como falha de sessão: quem
            # chama fecha, espera o portal e abre o navegador de novo.
            raise LoginNaoConcluido(f"rede na troca de perfil — {type(e).__name__}: "
                                    f"{str(e)[:200]}") from None
        raise PerfilRecusado(f"{type(e).__name__}: {e}") from None
    if not ok:
        raise PerfilRecusado(ultima_recusa_de_perfil() or "perfil não confirmado")
    sessao.cnpj_ativo = cnpj
