"""Caixa Postal do e-CAC: abrir as mensagens IMPORTANTES não lidas que travam a empresa.

REGRA DO USUÁRIO (19/11/2026), no lugar da anterior ("nunca abrir"): quando o
aviso de mensagens importantes aparece, a automação abre a Caixa Postal, abre
TODAS as importantes ainda não lidas (abrir dá ciência ao contribuinte — é a
intenção) e anota cada uma na aba "Mensagens importantes abertas" da planilha
(CNPJ, empresa, certificado, assunto). Depois volta ao PER/DCOMP e segue com as
linhas da empresa.

Porte do RevisaoCafes (`automation/mensagens/portal.py`), que já faz isso no
e-CAC real:
  - a lista é lida da RESPOSTA de `/caixapostal/api/mensagens` (campos
    `relevante`, `lida`, `isn`, `assunto`), depois do filtro da tela "Exibir
    apenas mensagens importantes" + "Não lida" — não se adivinha o que é
    importante pelo visual;
  - cada uma é aberta pelo link cujo TEXTO é o assunto (`.../mensagens/<isn>`);
  - antes de tudo, o perfil ativo tem de ser o CNPJ da empresa: a Caixa Postal
    de outra empresa nunca é aberta;
  - nenhum link nem anexo de DENTRO da mensagem é clicado.
No fim, a lista é refeita: sobrando importante não lida, é erro (quem chama
volta à regra antiga para a empresa: marca a linha e segue).
"""
from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .config import CAIXA_POSTAL_URL
from .formulario_perdcomp import navegador_fechou
from .sessao import cnpj_do_perfil_ativo

SEL_IFRAME = "#frmApp"
SEL_LISTA = "app-lista-mensagens"
SEL_PULAR_TUTORIAL = "a[aria-label='Pular Tutorial']"
SEL_VOLTAR = "button:has-text('Voltar')"
SEL_ABRIR_FILTRO = "i.fa-filter[title='Filtros']"
SEL_SELECT = "ng-select"
SEL_OPCOES = "ng-dropdown-panel .ng-option"
SEL_TITULO = ".fieldset-header legend"
CAMINHO_DA_LISTA = "/caixapostal/api/mensagens"
OPCAO_IMPORTANTES = "exibir apenas mensagens importantes"
OPCAO_NAO_LIDA = "nao lida"

TEMPO_IDA_MS = 30_000
TEMPO_LISTA_MS = 20_000
TEMPO_OPCOES_MS = 5_000
TEMPO_MENSAGEM_MS = 30_000
PAUSA_MS = 800
# Voltas "lista -> abrir as que vieram": a lista é paginada/atualizada pelo
# portal; a cada volta só entram as que ainda aparecem como não lidas.
MAX_RODADAS = 3

# O título da mensagem aberta: o <legend> sem o "expandido" (sr-only).
JS_TITULO = r"""(legenda) => {
  const copia = legenda.cloneNode(true);
  copia.querySelectorAll('.sr-only').forEach((x) => x.remove());
  return copia.innerText.replace(/\s+/g, ' ').trim();
}"""


class CaixaPostalNaoReconhecida(Exception):
    """A Caixa Postal não ficou como esperado (outro CNPJ, filtro sem resposta,
    mensagem que não abre...). Nada mais é aberto."""


@dataclass(frozen=True)
class MensagemDaLista:
    isn: str            # id da mensagem: o link é ".../mensagens/<isn>"
    assunto: str
    data_envio: str = ""


def normal(texto: str) -> str:
    """Sem acento, sem caixa e com os espaços colapsados (para comparar textos da tela)."""
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", str(texto or ""))
                         if not unicodedata.combining(c))
    return " ".join(sem_acento.casefold().split())


def importantes_nao_lidas(resposta: object) -> list[MensagemDaLista]:
    """As mensagens da resposta da lista marcadas como importantes ("relevante")
    e não lidas, na ordem da lista. Sem os campos, ValueError."""
    itens = resposta.get("mensagens") if isinstance(resposta, Mapping) else resposta
    if not isinstance(itens, list):
        raise ValueError("a resposta da Caixa Postal não trouxe a lista de mensagens")
    achadas = []
    for item in itens:
        if not isinstance(item, Mapping) or not {"relevante", "lida", "isn"} <= set(item):
            raise ValueError("mensagem da Caixa Postal sem os campos relevante/lida/isn")
        if item["relevante"] is True and item["lida"] is False:
            achadas.append(MensagemDaLista(str(item["isn"]),
                                           " ".join(str(item.get("assunto") or "").split()),
                                           str(item.get("dataEnvio") or "")))
    return achadas


def _pular_tutorial(quadro) -> None:
    try:
        quadro.locator(SEL_PULAR_TUTORIAL).first.click(timeout=2_000)
    except Exception:  # noqa: BLE001, S110 — sem tutorial, nada a pular
        pass


def _escolher(page, quadro, alvo: str, *, prefixo: bool) -> None:
    """No painel de filtros, o <ng-select> que tem a opção `alvo` passa a
    mostrá-la. Os outros selects são abertos, olhados e fechados sem escolha."""
    selects = quadro.locator(SEL_SELECT)
    bate = (lambda t: t.startswith(alvo)) if prefixo else (lambda t: t == alvo)
    for i in range(selects.count()):
        select = selects.nth(i)
        if not select.is_visible():
            continue
        select.locator(".ng-select-container").first.click(timeout=TEMPO_OPCOES_MS)
        opcoes = quadro.locator(SEL_OPCOES)
        try:
            opcoes.first.wait_for(state="visible", timeout=TEMPO_OPCOES_MS)
        except Exception as e:  # noqa: BLE001 — select sem opções: o próximo
            if navegador_fechou(e):
                raise
            page.keyboard.press("Escape")
            continue
        textos = [normal(t) for t in opcoes.all_inner_texts()]
        achada = next((k for k, t in enumerate(textos) if bate(t)), None)
        if achada is None:
            page.keyboard.press("Escape")
            continue
        opcoes.nth(achada).click(timeout=TEMPO_OPCOES_MS)
        page.wait_for_timeout(300)
        valor = normal(select.locator(".ng-value-label").first.inner_text(timeout=TEMPO_OPCOES_MS))
        if not bate(valor):
            raise CaixaPostalNaoReconhecida(f"o filtro '{alvo}' não ficou marcado")
        return
    raise CaixaPostalNaoReconhecida(f"o filtro da Caixa Postal não tem a opção '{alvo}'")


def listar(page, cnpj: str) -> list[MensagemDaLista]:
    """Vai para a Caixa Postal, confere de quem é, filtra (importantes + não
    lidas) e lê a lista da resposta do portal. Nada é aberto."""
    page.goto(CAIXA_POSTAL_URL, wait_until="domcontentloaded", timeout=TEMPO_IDA_MS)
    quadro = page.frame_locator(SEL_IFRAME)
    quadro.locator(SEL_LISTA).first.wait_for(state="visible", timeout=TEMPO_LISTA_MS)
    _pular_tutorial(quadro)
    dono = cnpj_do_perfil_ativo(page, timeout=TEMPO_LISTA_MS)
    if dono != cnpj:
        raise CaixaPostalNaoReconhecida(
            f"a Caixa Postal aberta é de {dono or '(CNPJ não lido)'}, e não de {cnpj}: nada é aberto")
    # O painel do filtro pode demorar a abrir (BARON, 19/11/2026: só o "Exibir:
    # 20" da paginação estava visível). Espera o botão "Filtrar" e tenta de novo.
    filtrar = quadro.get_by_role("button", name="Filtrar", exact=True).first
    for tentativa in range(1, 5):
        try:
            if not filtrar.is_visible():
                quadro.locator(SEL_ABRIR_FILTRO).first.click(timeout=TEMPO_LISTA_MS)
                filtrar.wait_for(state="visible", timeout=10_000)
            page.wait_for_timeout(1_000)
            _escolher(page, quadro, OPCAO_IMPORTANTES, prefixo=True)
            break
        except Exception as e:  # noqa: BLE001 — painel ainda abrindo: de novo
            if navegador_fechou(e) or tentativa == 4:
                raise
            page.keyboard.press("Escape")
            page.wait_for_timeout(2_000)
    _escolher(page, quadro, OPCAO_NAO_LIDA, prefixo=False)
    try:
        with page.expect_response(lambda r: CAMINHO_DA_LISTA in r.url and r.ok,
                                  timeout=TEMPO_LISTA_MS) as resposta:
            quadro.get_by_role("button", name="Filtrar", exact=True).first.click(
                timeout=TEMPO_LISTA_MS)
        dados = resposta.value.json()
    except Exception as e:  # noqa: BLE001 — sem a resposta do filtro, nada se abre
        if navegador_fechou(e):
            raise
        raise CaixaPostalNaoReconhecida(
            f"o filtro da Caixa Postal não trouxe a lista ({type(e).__name__})") from None
    page.wait_for_timeout(PAUSA_MS)
    try:
        return importantes_nao_lidas(dados)
    except ValueError as e:
        raise CaixaPostalNaoReconhecida(str(e)) from None


def _listar_insistindo(page, cnpj: str, tentativas: int = 3) -> list[MensagemDaLista]:
    """`listar`, de novo depois de uma pausa se o portal falhar ("Erro ao
    listar mensagem(ns)", CASA DE CARNES, 19/11/2026). A Caixa Postal de outro
    CNPJ não é repetida."""
    for tentativa in range(1, tentativas + 1):
        try:
            return listar(page, cnpj)
        except Exception as e:  # noqa: BLE001
            if navegador_fechou(e) or "nada é aberto" in str(e) or tentativa == tentativas:
                raise
            print(f"  -> [CAIXA POSTAL] Lista nao veio ({type(e).__name__}); tentando de novo "
                  f"({tentativa + 1}/{tentativas})...")
            page.wait_for_timeout(5_000)
    raise AssertionError("inalcancavel")


def _links_do_assunto(quadro, mensagem: MensagemDaLista) -> list:
    """Os links da mensagem (`.../mensagens/<isn>`) cujo TEXTO é o assunto (a
    linha tem outros links para a mesma mensagem, como o do remetente)."""
    todos = quadro.locator(f'a[href$="/mensagens/{mensagem.isn}"]')
    procurado = normal(mensagem.assunto)
    return [todos.nth(i) for i in range(todos.count())
            if normal(todos.nth(i).inner_text(timeout=TEMPO_LISTA_MS)) == procurado]


def voltar(page) -> None:
    try:
        page.frame_locator(SEL_IFRAME).locator(SEL_VOLTAR).first.click(timeout=5_000)
    except Exception as e:  # noqa: BLE001 — a próxima ida à lista refaz o filtro
        if navegador_fechou(e):
            raise


def abrir(page, cnpj: str, mensagem: MensagemDaLista) -> tuple[bool, str]:
    """Abre UMA mensagem pelo link do assunto e lê o título. (abriu de
    verdade — o título apareceu —, título). Volta para a lista."""
    quadro = page.frame_locator(SEL_IFRAME)
    links = _links_do_assunto(quadro, mensagem)
    if len(links) != 1:
        listar(page, cnpj)
        links = _links_do_assunto(quadro, mensagem)
    if len(links) != 1:
        raise CaixaPostalNaoReconhecida(
            f"a mensagem '{mensagem.assunto[:80]}' não está (ou está repetida) na lista")
    links[0].click(timeout=TEMPO_LISTA_MS)
    try:
        legenda = quadro.locator(SEL_TITULO).first
        legenda.wait_for(state="visible", timeout=TEMPO_MENSAGEM_MS)
        page.wait_for_timeout(PAUSA_MS)
        titulo = legenda.evaluate(JS_TITULO, timeout=TEMPO_MENSAGEM_MS) or ""
        aberta = True
    except Exception as e:  # noqa: BLE001 — a próxima lista diz se ela foi aberta
        if navegador_fechou(e):
            raise
        titulo, aberta = "", False
    voltar(page)
    return aberta, " ".join(str(titulo).split())


def abrir_todas(page, cnpj: str, *, ao_abrir: Callable[[str, str], None]) -> int:
    """Abre todas as importantes não lidas da empresa `cnpj`. `ao_abrir(isn,
    assunto)` é chamado UMA vez por mensagem aberta, logo depois de abri-la (a
    anotação na planilha não espera o fim). Devolve quantas foram abertas.
    Levanta CaixaPostalNaoReconhecida se sobrar importante não lida."""
    anotadas: set[str] = set()
    sem_confirmacao: dict[str, MensagemDaLista] = {}

    def _anotar(mensagem: MensagemDaLista, titulo: str = "") -> None:
        if mensagem.isn not in anotadas:
            anotadas.add(mensagem.isn)
            ao_abrir(mensagem.isn, mensagem.assunto or titulo)

    def _conferir(lista: list[MensagemDaLista]) -> None:
        # Clicada sem o título na tela: se saiu das não lidas, foi aberta.
        ainda = {m.isn for m in lista}
        for isn, mensagem in list(sem_confirmacao.items()):
            if isn not in ainda:
                _anotar(mensagem)
                sem_confirmacao.pop(isn)

    for _rodada in range(MAX_RODADAS):
        lista = _listar_insistindo(page, cnpj)
        _conferir(lista)
        if not lista:
            return len(anotadas)
        print(f"  -> [CAIXA POSTAL] {len(lista)} mensagem(ns) importante(s) nao lida(s); abrindo...")
        for mensagem in lista:
            aberta, titulo = abrir(page, cnpj, mensagem)
            if aberta:
                print(f"     aberta: {(mensagem.assunto or titulo)[:120]}")
                sem_confirmacao.pop(mensagem.isn, None)
                _anotar(mensagem, titulo)
            else:
                sem_confirmacao[mensagem.isn] = mensagem
    restantes = _listar_insistindo(page, cnpj)
    _conferir(restantes)
    if restantes:
        raise CaixaPostalNaoReconhecida(
            f"{len(restantes)} mensagem(ns) importante(s) continuam nao lidas depois de "
            f"{MAX_RODADAS} voltas")
    return len(anotadas)
