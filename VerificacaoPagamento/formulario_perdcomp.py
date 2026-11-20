"""Tela "Novo Documento" do PERDCOMP-WEB e a escolha "Declaração de Compensação".

Até aqui o fluxo é o das Protocolações de Restituição e Ressarcimento; a
diferença é o tipo de documento: em vez de "Pedido de Restituição"/"Pedido de
Ressarcimento", "Declaração de Compensação".

POR QUE O CLIQUE NO TIPO DE DOCUMENTO TEM UM MÓDULO INTEIRO DE CUIDADO
-----------------------------------------------------------------------
HTML real da tela (capturado na Restituição, debug_telas/check_fase3_*_frame1):

    <label for="tipoDocumento">Que documento deseja criar?</label>
    <label class="radio-inline">
      <input type="radio" id="tipoDocumento" name="tipoDocumento">
      <span><i class="icon-radio" data-value="3"></i> Declaração de Compensação<br></span>
    </label>
    ... data-value="2" Pedido de Restituição, "1" Ressarcimento,
        "4" Reembolso, "5" Cancelamento

  - Os CINCO radios têm o MESMO id e name ("tipoDocumento") e nenhum `value`:
    nem `#tipoDocumento` nem `input[value=...]` distinguem as opções. O único
    marcador estável é `i.icon-radio[data-value="3"]`; o texto é conferido
    junto, para o caso de o app renumerar os data-value.
  - O que travou as irmãs em produção (log da Restituição, 20/07/2026): o
    clique esperou 20 s e estourou com
        <div class="ui-widget-overlay"></div> intercepts pointer events
    — um overlay do PrimeNG (carregamento/modal) por cima do formulário.
    Por isso, antes de clicar, esperamos o rótulo ficar realmente "clicável"
    (o elemento no topo daquele ponto da tela é o próprio rótulo).
  - Duplo clique PIORA (registrado na Restituição: o campo seguinte deixou de
    aparecer). Então: UM clique por tentativa, conferência, e só depois — se
    a tela não reagiu — a próxima estratégia.
  - O DOM do PERDCOMP-WEB guarda telas antigas escondidas: o rótulo usado é
    sempre o VISÍVEL.

Conferência: o <input> da opção ficou marcado e o formulário reativo mostrou a
pergunta seguinte ("Documento Retificador?", `label[for='tipoRetificadora']`).
O mesmo mecanismo (`clicar_radio_confirmado`) responde o "Não" do Retificador.

Depois do tipo, o resto da identificação (passos enviados pelo usuário em
18/11/2026): Retificador = Não, Tipo de Crédito pela coluna K (PIS/COFINS),
Apelido fixo, "Outra Qualificação", "O crédito já foi detalhado em PER/DCOMP
anterior", o número da coluna M no campo com máscara, e "Prosseguir" — ver
`preencher_identificacao`.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from .config import APELIDO_DOCUMENTO, FRAME_PERDCOMP, SELETOR_NAV_NOVO_DOCUMENTO

TEXTO_DECLARACAO_COMPENSACAO = "Declaração de Compensação"
DATA_VALUE_DECLARACAO_COMPENSACAO = "3"

SELETOR_OPCOES_TIPO_DOCUMENTO = "label.radio-inline:has(input[name='tipoDocumento'])"
SELETOR_OPCAO_DCOMP = (
    f"label.radio-inline:has(i.icon-radio[data-value='{DATA_VALUE_DECLARACAO_COMPENSACAO}'])"
)
# Pergunta que o formulário reativo mostra depois que o tipo é escolhido.
SELETOR_REACAO_TIPO_DOCUMENTO = "label[for='tipoRetificadora']"

# Camadas que já foram vistas cobrindo o formulário: o overlay do PrimeNG (o
# do erro real) e o overlay dos modais próprios do PERDCOMP-WEB.
SELETORES_BLOQUEIO = (".ui-widget-overlay", ".perdcomp-modal-overlay")

# Quanto esperar um overlay/carregamento sair antes de tentar mesmo assim.
ESPERA_BLOQUEIO_MS = 30_000
# Quanto esperar a tela reagir depois de cada clique.
ESPERA_REACAO_MS = 6_000
# Prazo do clique de verdade no rótulo (estratégia 1) e do evento direto (3).
TIMEOUT_CLIQUE_MS = 10_000

SELETOR_BTN_PROSSEGUIR = "button[name='btnProsseguir']"


# ── Erros ────────────────────────────────────────────────────────────────────

class TelaNovoDocumentoIndisponivel(Exception):
    """A tela "Novo Documento" (pergunta 'Que documento deseja criar?') não abriu."""


class BotaoNaoClicado(Exception):
    """Nenhuma das estratégias de clique funcionou no botão (ver `clicar_botao`)."""


class ErroGenericoPerdcompWeb(Exception):
    """O modal "#genericError" ("Não é possível prosseguir neste momento. Tente
    novamente mais tarde.") está na tela. O "Ok" dele recarrega o app e perde o
    documento em andamento — mesmo tratamento das Protocolações."""


def navegador_fechou(erro) -> bool:
    """True se o erro indica navegador/contexto/página FECHADO.

    Com o navegador morto não adianta insistir: só atrasaria a reabertura e
    esconderia a causa no log. Mesma regra (deliberadamente abrangente) das
    Protocolações."""
    texto = erro if isinstance(erro, str) else f"{type(erro).__name__}: {erro}"
    t = (texto or "").lower()
    return any(trecho in t for trecho in (
        "targetclosederror",
        "target page, context or browser",
        "target closed",
        "browser closed",
        "browser has been closed",
        "connection closed",
        "session closed",
        "has been closed",
    ))


# ── Utilitários de tela ──────────────────────────────────────────────────────

def _frame(page):
    return page.frame_locator(FRAME_PERDCOMP)


def _primeiro_visivel(locator):
    """O elemento VISÍVEL do locator (de trás para frente: o da tela ativa), ou
    None. `is_visible()` elemento a elemento, e não o pseudo-seletor
    `:visible` — na Restituição o `:visible` deixou de casar com o único botão
    da tela, que estava lá e visível."""
    try:
        total = locator.count()
    except Exception as e:
        if navegador_fechou(e):
            raise
        return None
    for i in reversed(range(total)):
        candidato = locator.nth(i)
        try:
            if candidato.is_visible():
                return candidato
        except Exception as e:
            if navegador_fechou(e):
                raise
    return None


def _esperar_visivel(locator, timeout_ms: int, passo_s: float = 0.25):
    """Espera até um elemento do locator ficar visível; devolve-o ou None."""
    limite = time.monotonic() + timeout_ms / 1000
    while True:
        alvo = _primeiro_visivel(locator)
        if alvo is not None or time.monotonic() >= limite:
            return alvo
        time.sleep(passo_s)


# Devolve "" se o próprio elemento está no topo do ponto de clique; senão uma
# descrição curta de quem está por cima (para o log).
_JS_QUEM_ESTA_POR_CIMA = """(el) => {
    el.scrollIntoView({block: 'center', inline: 'nearest'});
    const alvo = el.querySelector('span') || el;
    const r = alvo.getBoundingClientRect();
    if (!r.width || !r.height) return 'elemento sem tamanho (escondido)';
    const x = r.left + Math.min(r.width / 2, 24);
    const y = r.top + r.height / 2;
    const topo = document.elementFromPoint(x, y);
    if (!topo) return 'ponto fora da tela';
    if (el.contains(topo)) return '';
    const classes = (typeof topo.className === 'string' && topo.className.trim())
        ? '.' + topo.className.trim().split(/\\s+/).join('.') : '';
    return '<' + topo.tagName.toLowerCase() + classes + '>';
}"""


def esperar_ficar_clicavel(alvo, timeout_ms: int = ESPERA_BLOQUEIO_MS) -> str:
    """Espera o alvo ficar no TOPO da tela (sem overlay por cima).

    Devolve "" quando ficou clicável; senão a descrição do que continuou por
    cima ao fim do prazo (o chamador tenta mesmo assim, com uma estratégia que
    não depende do ponteiro)."""
    limite = time.monotonic() + timeout_ms / 1000
    avisou = False
    por_cima = ""
    while True:
        try:
            por_cima = alvo.evaluate(_JS_QUEM_ESTA_POR_CIMA)
        except Exception as e:
            if navegador_fechou(e):
                raise
            por_cima = f"não foi possível conferir ({type(e).__name__})"
        if not por_cima:
            return ""
        if not avisou:
            print(f"       -> aguardando liberar a tela: {por_cima} esta por cima do campo...")
            avisou = True
        if time.monotonic() >= limite:
            return por_cima
        time.sleep(0.3)


def clicar_botao(frame, seletor: str, timeout: int = 20_000, tentativas: int = 3,
                 descricao: str = "") -> None:
    """Clica num botão com insistência (porte da Restituição): escolhe o
    VISÍVEL, espera overlay sair, e cai para `dispatch_event('click')` quando o
    clique normal estoura — só se o botão estiver visível E habilitado (num
    botão escondido/desabilitado o evento "funciona" sem fazer nada)."""
    nome = descricao or seletor
    ultimo_erro: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        alvos = frame.locator(seletor)
        alvo = _primeiro_visivel(alvos) or alvos.last
        esperar_ficar_clicavel(alvo, timeout_ms=min(timeout, ESPERA_BLOQUEIO_MS))
        try:
            alvo.click(timeout=timeout)
            return
        except Exception as e:
            if navegador_fechou(e):
                raise
            ultimo_erro = e
            print(f"  -> [AVISO] Clique normal em {nome} falhou (tentativa {tentativa}/"
                  f"{tentativas}): {type(e).__name__}. Disparando o evento direto no elemento...")
        try:
            if alvo.is_visible() and alvo.is_enabled():
                alvo.dispatch_event("click", timeout=timeout)
                return
        except Exception as e:
            if navegador_fechou(e):
                raise
            ultimo_erro = e
    raise BotaoNaoClicado(
        f"Nao foi possivel clicar em {nome} apos {tentativas} tentativas: "
        f"{type(ultimo_erro).__name__}: {ultimo_erro}"
    )


def clicar_prosseguir(page, timeout: int = 20_000) -> None:
    """Clica "Prosseguir", recusando antes se o modal de erro genérico está na tela."""
    frame = _frame(page)
    if frame.locator("#genericError").is_visible():
        raise ErroGenericoPerdcompWeb(
            "PERDCOMP-WEB exibiu \"Não é possível prosseguir neste momento. "
            "Tente novamente mais tarde.\""
        )
    clicar_botao(frame, SELETOR_BTN_PROSSEGUIR, timeout, descricao="'Prosseguir'")


class OpcaoNaoSelecionada(Exception):
    """A opção pedida não ficou selecionada no <select> dentro do prazo."""


_JS_VALOR_DA_OPCAO = """(el, texto) => {
    const opt = Array.from(el.options).find(o => o.textContent.trim() === texto);
    return opt ? opt.value : null;
}"""

_JS_TEXTO_SELECIONADO = """(el) => (
    el.selectedIndex >= 0 && el.options[el.selectedIndex]
        ? el.options[el.selectedIndex].textContent.trim() : ""
)"""


def select_confere(select_locator, texto: str) -> bool:
    """Leitura-only: o <select> está com `texto` selecionado? (porte do Ressarcimento)"""
    try:
        return select_locator.evaluate(_JS_TEXTO_SELECIONADO, timeout=5_000) == texto
    except Exception as e:
        if navegador_fechou(e):
            raise
        return False


def selecionar_por_texto_visivel(select_locator, texto: str, timeout: int = 15_000) -> None:
    """Seleciona a <option> pelo texto visível e CONFERE (porte do Ressarcimento).

    Pelo texto porque o Angular gera `value` posicionais e instáveis ("3: Object").
    Ler-e-selecionar é repetido dentro da mesma janela de tempo: o PERDCOMP-WEB
    repopula as <option> de forma assíncrona, e um value lido antes de um
    re-render deixa de existir (bug real no Ressarcimento, 21/07/2026)."""
    limite = time.monotonic() + timeout / 1000
    ultimo_erro: Exception | None = None
    achou = False
    while time.monotonic() < limite:
        restante = max(1_000, int((limite - time.monotonic()) * 1000))
        try:
            select_locator.wait_for(state="visible", timeout=restante)
            valor = select_locator.evaluate(_JS_VALOR_DA_OPCAO, texto)
            if valor is None:
                time.sleep(0.25)
                continue
            achou = True
            select_locator.select_option(value=valor, timeout=min(5_000, restante))
            if select_locator.evaluate(_JS_TEXTO_SELECIONADO) == texto:
                return
        except Exception as e:
            if navegador_fechou(e):
                raise
            ultimo_erro = e
        time.sleep(0.25)
    if not achou:
        raise OpcaoNaoSelecionada(f"Opção '{texto}' não apareceu no <select> em {timeout / 1000:.0f}s.")
    raise OpcaoNaoSelecionada(
        f"Opção '{texto}' existe, mas não permaneceu selecionada em {timeout / 1000:.0f}s. "
        f"Último erro: {type(ultimo_erro).__name__}: {ultimo_erro}"
    )


# ── Radio com conferência (o mecanismo do tipo de documento, generalizado) ───

class RadioNaoSelecionado(Exception):
    """Um radio não ficou marcado depois de todas as estratégias."""


class TipoDocumentoNaoSelecionado(RadioNaoSelecionado):
    """'Declaração de Compensação' não ficou selecionada."""


class CampoNaoEncontrado(Exception):
    """Um campo esperado do formulário não apareceu na tela."""


class CampoNaoConfirmado(Exception):
    """O campo não manteve o valor esperado depois de reescrever e reler."""


class ProsseguirNaoAvancou(Exception):
    """'Prosseguir' foi clicado, mas o formulário continuou na mesma tela."""


_JS_MARCADA = """(el, seletor) => {
    const input = el.querySelector(seletor);
    return !!(input && input.checked);
}"""


def _marcada(alvo, seletor_input: str) -> bool:
    try:
        return bool(alvo.evaluate(_JS_MARCADA, seletor_input))
    except Exception as e:
        if navegador_fechou(e):
            raise
        return False


def _visivel(page, seletor: str) -> bool:
    return _primeiro_visivel(_frame(page).locator(seletor)) is not None


def _esperar_confirmacao(alvo, seletor_input: str, reagiu, espera_ms: int) -> tuple[bool, bool]:
    """(marcada, reagiu) — termina assim que a tela reagir, ou no prazo."""
    limite = time.monotonic() + espera_ms / 1000
    while True:
        marcada = _marcada(alvo, seletor_input)
        ok = reagiu()
        if ok or time.monotonic() >= limite:
            return marcada, ok
        time.sleep(0.25)


def _estrategias(alvo, seletor_input: str):
    """Uma por tentativa, da mais natural para a mais direta.

    1. Clique de verdade no rótulo (o que um usuário faz). Falha se houver
       overlay por cima — por isso ele vem depois da espera de "clicável".
    2. `input.click()` via JS: dispara a ativação nativa do radio (marca,
       'click', 'input', 'change') sem depender do ponteiro — passa por baixo de
       um overlay que não saiu. (O JS roda no mundo isolado do patchright, mas o
       DOM é o mesmo: os ouvintes do Angular recebem o evento.)
    3. Evento 'click' despachado direto no <input> pelo Playwright.
    """
    entrada = alvo.locator(seletor_input)
    return [
        ("clique no rotulo", lambda: alvo.click(timeout=TIMEOUT_CLIQUE_MS)),
        ("input.click() via JS",
         lambda: alvo.evaluate("(el, s) => el.querySelector(s).click()", seletor_input)),
        ("evento click no input", lambda: entrada.dispatch_event("click", timeout=TIMEOUT_CLIQUE_MS)),
    ]


def clicar_radio_confirmado(alvo, *, seletor_input: str, reagiu, nome: str, proximo: str,
                            diagnostico=None, rotulo_diagnostico: str = "radio",
                            erro=RadioNaoSelecionado) -> None:
    """Marca o radio do rótulo `alvo` e confere que a tela reagiu (`reagiu()`).

    UM clique por estratégia; a próxima só entra se a tela não reagiu. Antes
    de cada uma, espera o rótulo ficar no topo da tela (sem overlay). Ver o
    docstring do módulo para o porquê de cada cuidado."""
    marcada, ok = _esperar_confirmacao(alvo, seletor_input, reagiu, espera_ms=0)
    if marcada and ok:
        print(f"  -> '{nome}' ja estava selecionado.")
        return

    falhas: list[str] = []
    for numero, (estrategia, acao) in enumerate(_estrategias(alvo, seletor_input), start=1):
        por_cima = esperar_ficar_clicavel(alvo, ESPERA_BLOQUEIO_MS)
        if por_cima:
            print(f"  -> [AVISO] {por_cima} continua por cima de '{nome}' apos "
                  f"{ESPERA_BLOQUEIO_MS / 1000:.0f}s; tentando assim mesmo ({estrategia}).")
        try:
            acao()
        except Exception as e:
            if navegador_fechou(e):
                raise
            falhas.append(f"{estrategia}: {type(e).__name__}")
            print(f"  -> [AVISO] '{nome}': '{estrategia}' falhou ({type(e).__name__}). "
                  "Tentando a proxima estrategia...")
            continue

        marcada, ok = _esperar_confirmacao(alvo, seletor_input, reagiu, ESPERA_REACAO_MS)
        if ok:
            print(f"  -> '{nome}' selecionado (estrategia {numero}: {estrategia}).")
            return
        falhas.append(f"{estrategia}: {'marcou, mas a tela nao reagiu' if marcada else 'nao marcou'}")
        situacao = (f"ficou marcado, mas {proximo} nao apareceu" if marcada else "nao ficou marcado")
        print(f"  -> [AVISO] '{nome}': apos '{estrategia}' {situacao} "
              f"em {ESPERA_REACAO_MS / 1000:.0f}s.")

    if _marcada(alvo, seletor_input):
        # O DOM diz que está marcado, mas o passo seguinte não apareceu. Segue:
        # se o passo seguinte de fato não existir, ele mesmo falha com erro
        # claro — e o retrato da tela fica salvo para conferência.
        print(f"  -> [AVISO] '{nome}' esta marcado, mas {proximo} nao apareceu. "
              "Seguindo; tela salva para conferencia.")
        if diagnostico is not None:
            diagnostico(f"{rotulo_diagnostico}_marcada_sem_reacao")
        return

    if diagnostico is not None:
        diagnostico(f"{rotulo_diagnostico}_nao_selecionada")
    raise erro(f"'{nome}' nao ficou selecionado: " + "; ".join(falhas))


# ── Novo Documento + Declaração de Compensação ───────────────────────────────

def abrir_novo_documento(page, timeout: int = 30_000) -> None:
    """Clica "Novo Documento" (barra lateral, pelo ícone — ver config) e espera
    a pergunta "Que documento deseja criar?". Sempre clica, como nas
    Protocolações: cada documento começa por ele."""
    frame = _frame(page)
    clicar_botao(frame, SELETOR_NAV_NOVO_DOCUMENTO, timeout, descricao="'Novo Documento'")
    print("  -> 'Novo Documento' clicado.")
    if _esperar_visivel(frame.locator(SELETOR_OPCOES_TIPO_DOCUMENTO), timeout_ms=timeout) is None:
        raise TelaNovoDocumentoIndisponivel(
            f"A pergunta 'Que documento deseja criar?' não apareceu em {timeout / 1000:.0f}s "
            "depois de clicar 'Novo Documento'."
        )
    # O app ainda busca dados depois de desenhar a tela, e ao receber RECRIA o
    # formulário (linhas 71/73, 18/11/2026): só segue com a página quieta.
    aguardar_pagina_pronta(page)


def _texto_normalizado(alvo) -> str:
    try:
        return " ".join((alvo.inner_text(timeout=5_000) or "").split())
    except Exception as e:
        if navegador_fechou(e):
            raise
        return ""


def _localizar_opcao_dcomp(page, timeout: int):
    """O rótulo VISÍVEL de "Declaração de Compensação".

    Primeiro pelo marcador estável (data-value="3") — conferindo o texto, para
    não clicar em outra opção se o app renumerar. Se o marcador não achar a
    opção certa, cai para o texto do rótulo."""
    frame = _frame(page)
    alvo = _esperar_visivel(frame.locator(SELETOR_OPCAO_DCOMP), timeout_ms=timeout)
    if alvo is not None and TEXTO_DECLARACAO_COMPENSACAO in _texto_normalizado(alvo):
        return alvo
    if alvo is not None:
        print("  -> [AVISO] A opcao data-value=3 nao e 'Declaracao de Compensacao' "
              "(o app mudou a numeracao?). Localizando pelo texto.")
    pelo_texto = frame.locator(SELETOR_OPCOES_TIPO_DOCUMENTO).filter(
        has_text=TEXTO_DECLARACAO_COMPENSACAO)
    alvo = _esperar_visivel(pelo_texto, timeout_ms=5_000)
    if alvo is None:
        raise TipoDocumentoNaoSelecionado(
            f"A opcao '{TEXTO_DECLARACAO_COMPENSACAO}' nao esta visivel na tela 'Novo Documento'."
        )
    return alvo


# Seleção CONFIRMADA, lida ao vivo em 18/11/2026: com a Declaração escolhida, o
# radio dela fica marcado e a página põe `tipo-documento-disabled` nas OUTRAS
# quatro opções. (Numa página sem essa classe — réplica de teste — vale o radio.)
_JS_DCOMP_CONFIRMADA = """() => {
    const labels = Array.from(document.querySelectorAll('label.radio-inline'))
        .filter(l => l.querySelector("input[name='tipoDocumento']") && l.getBoundingClientRect().width > 0);
    const dcomp = labels.find(l => l.textContent.includes('Declaração de Compensação'));
    if (!dcomp || !dcomp.querySelector('input').checked) return false;
    const outros = labels.filter(l => l !== dcomp);
    const desab = (l) => l.parentElement.classList.contains('tipo-documento-disabled');
    return outros.some(desab) ? outros.every(desab) : true;
}"""
TENTATIVAS_DCOMP = 3


def dcomp_confirmada(page) -> bool:
    try:
        return bool(_frame(page).locator("body").evaluate(_JS_DCOMP_CONFIRMADA, timeout=5_000))
    except Exception as e:
        if navegador_fechou(e):
            raise
        return False


def selecionar_declaracao_compensacao(page, timeout: int = 30_000, diagnostico=None) -> None:
    """Escolhe "Declaração de Compensação" em "Que documento deseja criar?".

    O que a página mostra (leitura ao vivo, 18/11/2026): o radio de cada opção
    é INVISÍVEL (opacity 0) e o que recebe o clique é o ícone `i.icon-radio`,
    no centro do botão. Clicar com a página ainda carregando (logo depois do
    "Novo Documento") fazia o app RECRIAR o formulário vazio por cima.

    Por isso: página quieta -> um clique -> conferência (radio marcado, as outras
    opções desabilitadas e "Documento Retificador?" na tela) -> página quieta de
    novo -> conferência de novo. Se o formulário reiniciou, clica outra vez."""
    def _confirmada() -> bool:
        return dcomp_confirmada(page) and _visivel(page, SELETOR_REACAO_TIPO_DOCUMENTO)

    for tentativa in range(1, TENTATIVAS_DCOMP + 1):
        aguardar_pagina_pronta(page)
        alvo = _localizar_opcao_dcomp(page, timeout)
        clicar_radio_confirmado(
            alvo, seletor_input="input[name='tipoDocumento']", reagiu=_confirmada,
            nome=TEXTO_DECLARACAO_COMPENSACAO, proximo="'Documento Retificador?'",
            diagnostico=diagnostico, rotulo_diagnostico="dcomp", erro=TipoDocumentoNaoSelecionado,
        )
        aguardar_pagina_pronta(page)
        if _confirmada():
            return
        print(f"  -> [AVISO] '{TEXTO_DECLARACAO_COMPENSACAO}' nao permaneceu selecionada (o formulario "
              f"reiniciou?). Selecionando de novo ({tentativa}/{TENTATIVAS_DCOMP})...")
        if diagnostico is not None and tentativa == 1:
            diagnostico("dcomp_nao_permaneceu")
    raise TipoDocumentoNaoSelecionado(
        f"'{TEXTO_DECLARACAO_COMPENSACAO}' nao permaneceu selecionada apos {TENTATIVAS_DCOMP} tentativas."
    )


# ── Identificação do documento (HTML real enviado pelo usuário, 18/11/2026) ──

# "Documento Retificador?*" — dois rótulos com o input DENTRO, mesmo id/name:
#   <label class="control control--radio">Não <input type="radio"
#          formcontrolname="tipoRetificadora" id="tipoRetificadora"
#          name="tipoRetificadora"><div class="control__indicator"></div></label>
SELETOR_INPUT_RETIFICADORA = "input[name='tipoRetificadora']"
SELETOR_TIPO_CREDITO = "#tipoCredito"
SELETOR_APELIDO = "#apelidoDocumento"
SELETOR_QUALIFICACAO = "#qualificacaoContribuinte"
SELETOR_DETALHAMENTO = "#tipoIdentificacaoCredito"
# "Número do PER/DCOMP Anterior que Detalha o Crédito": p-inputmask do PrimeNG,
# sem id nem formcontrolname no HTML enviado — o placeholder é o que o identifica.
MASCARA_PERDCOMP = "99999.99999.999999.9.9.99-9999"
SELETOR_PERDCOMP_ANTERIOR = f"input[placeholder='{MASCARA_PERDCOMP}']"

TEXTO_TIPO_CREDITO = {
    "PIS": "PIS/PASEP Não-Cumulativo - Ressarcimento/Compensação - PA a partir de Janeiro de 2014",
    "COFINS": "Cofins Não-Cumulativa - Ressarcimento/Compensação - PA a partir de Janeiro de 2014",
    # código 04 e coluna K sem PIS nem COFINS (INSS, IRPJ...): regra de 20/11/2026
    "PAGAMENTO INDEVIDO": "Pagamento Indevido ou a Maior",
}
TEXTO_QUALIFICACAO = "Outra Qualificação"
TEXTO_DETALHAMENTO = "O crédito já foi detalhado em PER/DCOMP anterior"

# Quanto esperar a próxima tela depois de um "Prosseguir"/"OK"/"Confirmar".
ESPERA_AVANCO_MS = 20_000


# ── Campos genéricos (com conferência) ───────────────────────────────────────

def campo_visivel(page, seletor: str, rotulo: str, timeout: int = 20_000):
    """O elemento VISÍVEL do seletor (o DOM guarda telas antigas com o mesmo id)."""
    alvo = _esperar_visivel(_frame(page).locator(seletor), timeout_ms=timeout)
    if alvo is None:
        raise CampoNaoEncontrado(f"{rotulo}: o campo nao apareceu na tela.")
    return alvo


def selecionar(page, seletor: str, texto: str, rotulo: str, timeout: int = 20_000) -> None:
    """Escolhe `texto` no <select> visível, conferindo (ver selecionar_por_texto_visivel)."""
    selecionar_por_texto_visivel(campo_visivel(page, seletor, rotulo, timeout), texto, timeout)


def _ler_input(loc) -> str:
    """Lê o valor do <input>, 2x: um "" falso durante re-render do Angular faria
    a conferência reescrever um campo que já estava certo."""
    for tentativa in (1, 2):
        try:
            return loc.input_value(timeout=5_000)
        except Exception as e:
            if navegador_fechou(e):
                raise
            if tentativa == 1:
                time.sleep(0.3)
    return ""


_JS_DEFINIR_VALOR = """(el, v) => {
    el.value = v;
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
}"""


def _normalizar_espacos(texto: str) -> str:
    return " ".join((texto or "").split())


def preencher_texto_confirmado(page, seletor: str, valor: str, rotulo: str, *, confere=None,
                               tentativas: int = 3, timeout: int = 20_000) -> None:
    """Preenche e CONFERE relendo; se não colou, força via JS (input/change).
    Em app Angular o `fill()` às vezes não registra (visto nas Protocolações).

    `confere(lido) -> bool`: comparação própria (ex.: campo de moeda que
    reformata '10,00'); padrão = texto igual, espaços normalizados."""
    alvo = campo_visivel(page, seletor, rotulo, timeout)
    if confere is None:
        def confere(lido: str) -> bool:
            return _normalizar_espacos(lido) == _normalizar_espacos(valor)

    def _ok() -> bool:
        return confere(_ler_input(alvo))

    for tentativa in range(1, tentativas + 1):
        try:
            alvo.fill(valor, timeout=timeout)
            alvo.dispatch_event("blur")
        except Exception as e:
            if navegador_fechou(e):
                raise
        if _ok():
            return
        try:
            alvo.evaluate(_JS_DEFINIR_VALOR, valor)
            alvo.dispatch_event("blur")
        except Exception as e:
            if navegador_fechou(e):
                raise
        if _ok():
            return
        print(f"       -> [revisao] {rotulo}: nao confirmou (tentativa {tentativa}/{tentativas}).")
        time.sleep(0.4)
    raise CampoNaoConfirmado(f"{rotulo}: o campo nao manteve o valor apos {tentativas} tentativas.")


def valor_monetario(texto: str):
    """'1.234,56' / '10,00' / '1' -> Decimal; None se não for número."""
    from decimal import Decimal, InvalidOperation

    limpo = (texto or "").strip().replace("R$", "").replace(" ", "")
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    try:
        return Decimal(limpo)
    except (InvalidOperation, ValueError):
        return None


def preencher_valor_confirmado(page, seletor: str, valor: str, rotulo: str,
                               timeout: int = 20_000) -> None:
    """Campo de moeda (perdcompcurrency): preenche "10,00" e confere pelo VALOR
    (a diretiva pode exibir "10,00", "10.00" ou "R$ 10,00")."""
    esperado = valor_monetario(valor)
    preencher_texto_confirmado(page, seletor, valor, rotulo, timeout=timeout,
                               confere=lambda lido: valor_monetario(lido) == esperado)


def _so_digitos(texto: str) -> str:
    return "".join(c for c in (texto or "") if c.isdigit())


def preencher_digitando(page, seletor: str, texto: str, rotulo: str, *, formatado: str = "",
                        timeout: int = 20_000) -> None:
    """Campo com máscara (p-inputmask, data, período): DIGITA tecla a tecla, como
    o operador, e confere pelos DÍGITOS. A máscara monta a pontuação sozinha e
    pode descartar um valor colado de uma vez — por isso colar (`fill`) e o JS
    só entram se a releitura não bater. `formatado`: o texto já com a pontuação,
    usado nessas alternativas (padrão: o próprio `texto`)."""
    esperado = _so_digitos(texto)
    formatado = formatado or texto
    alvo = campo_visivel(page, seletor, rotulo, timeout)
    esperar_ficar_clicavel(alvo, ESPERA_BLOQUEIO_MS)

    def digitar():
        alvo.click(timeout=TIMEOUT_CLIQUE_MS)
        alvo.press("Control+a")
        alvo.press("Backspace")
        alvo.press_sequentially(texto, delay=30)
        # Tab fecha o calendário do datepicker e dispara o blur da máscara.
        alvo.press("Tab")

    def colar_formatado():
        alvo.fill(formatado, timeout=TIMEOUT_CLIQUE_MS)
        alvo.dispatch_event("blur")

    def via_js():
        alvo.evaluate(_JS_DEFINIR_VALOR, formatado)
        alvo.dispatch_event("blur")

    lido = ""
    for estrategia, acao in (("digitacao", digitar), ("fill formatado", colar_formatado),
                             ("valor via JS", via_js)):
        try:
            acao()
        except Exception as e:
            if navegador_fechou(e):
                raise
            print(f"       -> [revisao] {rotulo}: '{estrategia}' falhou ({type(e).__name__}).")
            continue
        lido = _so_digitos(_ler_input(alvo))
        if lido == esperado:
            print(f"  -> {rotulo} preenchido ({estrategia}).")
            return
        # Só tamanhos: o campo pode ser CPF/número de documento (não vai para o log).
        print(f"       -> [revisao] {rotulo}: apos '{estrategia}' o campo ficou com "
              f"{len(lido)} digito(s), esperado {len(esperado)}.")
    raise CampoNaoConfirmado(
        f"{rotulo}: o campo nao manteve os {len(esperado)} digitos (ficou com {len(lido)})."
    )


def formatar_perdcomp(digitos: str) -> str:
    """'123...' (24 dígitos) -> '12345.12345.123456.1.1.12-1234' (a máscara da tela)."""
    if len(digitos) != 24 or not digitos.isdigit():
        raise ValueError(f"numero de PER/DCOMP deve ter 24 digitos (tem {len(digitos)})")
    d = digitos
    return f"{d[0:5]}.{d[5:10]}.{d[10:16]}.{d[16]}.{d[17]}.{d[18:20]}-{d[20:24]}"


def preencher_perdcomp_anterior(page, digitos: str, timeout: int = 20_000) -> None:
    """O "Número do PER/DCOMP Anterior" (coluna M), conferido nos 24 dígitos."""
    preencher_digitando(page, SELETOR_PERDCOMP_ANTERIOR, digitos, "PER/DCOMP anterior",
                        formatado=formatar_perdcomp(digitos), timeout=timeout)


def marcar_checkbox_confirmado(page, seletor: str, rotulo: str, timeout: int = 20_000) -> None:
    """Marca o checkbox e confere `checked`. Não clica se já está marcado (um
    segundo clique DESMARCARIA).

    1. `check()` do Playwright (clica e confere);
    2. `el.click()` via JS — passa por baixo de overlay;
    3. `checked = true` + evento 'change' — o que o fluxo original em UiPath
       fazia (NInjectJsScript) neste mesmo checkbox no Ressarcimento."""
    alvo = campo_visivel(page, seletor, rotulo, timeout)

    def marcado() -> bool:
        try:
            return bool(alvo.evaluate("(el) => el.checked"))
        except Exception as e:
            if navegador_fechou(e):
                raise
            return False

    estrategias = (
        ("check()", lambda: alvo.check(timeout=TIMEOUT_CLIQUE_MS)),
        ("click() via JS", lambda: alvo.evaluate("(el) => { if (!el.checked) el.click(); }")),
        ("checked via JS", lambda: alvo.evaluate(
            "(el) => { if (!el.checked) { el.checked = true;"
            " el.dispatchEvent(new Event('change', {bubbles: true})); } }")),
    )
    for estrategia, acao in estrategias:
        if marcado():
            print(f"  -> {rotulo}: marcado.")
            return
        esperar_ficar_clicavel(alvo, ESPERA_BLOQUEIO_MS)
        try:
            acao()
        except Exception as e:
            if navegador_fechou(e):
                raise
            print(f"       -> [revisao] {rotulo}: '{estrategia}' falhou ({type(e).__name__}).")
    if marcado():
        print(f"  -> {rotulo}: marcado.")
        return
    raise CampoNaoConfirmado(f"{rotulo}: o checkbox nao ficou marcado.")


# ── Avanço de tela ───────────────────────────────────────────────────────────

# TODOS os painéis de mensagens, juntos. Há mais de um no DOM (o do layout e o
# do documento); ler só "o primeiro visível" devolvia um painel VAZIO enquanto o
# aviso estava no outro — foi assim que o "Tipo do crédito ... diferente"
# (linhas 497/498) e o "Não é possível prosseguir" depois do Enviar (linha 509)
# passaram despercebidos em 18/11/2026. `innerText` já ignora o que está escondido.
_JS_MENSAGENS = """() => Array.from(document.querySelectorAll('perdcomp-painel-mensagens'))
    .map(e => (e.innerText || '').trim()).filter(t => t).join(' | ')"""


def mensagens_da_tela(page) -> str:
    """Texto dos painéis de mensagens do PERDCOMP-WEB (avisos e erros), curto."""
    try:
        texto = _frame(page).locator("body").evaluate(_JS_MENSAGENS, timeout=5_000) or ""
    except Exception as e:
        if navegador_fechou(e):
            raise
        return ""
    return " ".join(texto.split())[:500]


def esperar_algum(page, seletores, espera_ms: int, parar_se=None) -> str:
    """O primeiro dos `seletores` que ficar visível no prazo, ou "". Para antes
    (devolvendo "") se `parar_se()` ficar verdadeiro — ex.: um aviso de erro."""
    frame = _frame(page)
    limite = time.monotonic() + espera_ms / 1000
    while True:
        for seletor in seletores:
            if _primeiro_visivel(frame.locator(seletor)) is not None:
                return seletor
        if parar_se is not None and parar_se():
            return ""
        if time.monotonic() >= limite:
            return ""
        time.sleep(0.3)


# ── Antes de avançar: página parada + campos registrados ─────────────────────
#
# Execução real de 18/11/2026, linha 71: o mesmo preenchimento que o operador
# fez à mão e passou deu erro na automação — rápido demais, a página ainda não
# tinha registrado tudo. Regra do usuário: ANTES de cada "Prosseguir" (e do OK
# do termo e do "Confirmar" do débito), esperar a página terminar de carregar
# e conferir que TODOS os dados informados naquela tela foram registrados.

# Componentes de carregamento do PERDCOMP-WEB: vazios (<!---->) com a página
# parada, com conteúdo enquanto ela trabalha (HTML real, debug_telas/*_frame1).
_JS_CARREGANDO = """() => {
    const visivel = (e) => {
        const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
    };
    for (const sel of ['perdcomp-loading *', 'perdcomp-loading-modal *', '.p-blockui']) {
        for (const e of document.querySelectorAll(sel)) if (visivel(e)) return sel;
    }
    return '';
}"""
ESPERA_CARREGAMENTO_MS = 60_000
# Folga depois que a página para: o Angular termina a detecção de mudanças e as
# validações assíncronas do campo que acabou de ser preenchido.
FOLGA_ESTAVEL_MS = 300


def pagina_carregando(page) -> str:
    """O indicador de carregamento visível agora, ou ""."""
    try:
        return _frame(page).locator("body").evaluate(_JS_CARREGANDO, timeout=5_000) or ""
    except Exception as e:
        if navegador_fechou(e):
            raise
        return ""


class RastreadorRede:
    """Requisições XHR/fetch da página (iframes incluídos) ainda sem resposta.

    Execução real de 18/11/2026, linhas 71 e 73: depois do "Novo Documento" o
    PERDCOMP-WEB ainda buscava dados no servidor, e quando a resposta chegou
    RECRIOU o formulário vazio — por cima do que a automação já tinha marcado.
    Nenhum indicador visual mostrava esse carregamento; a rede mostra.

    Requisição pendurada há mais de JANELA_S (long-polling, telemetria) não
    conta: senão uma conexão eterna travaria toda espera."""

    JANELA_S = 15.0
    SOSSEGO_S = 0.5  # a rede precisa ficar quieta por este tempo

    def __init__(self, page) -> None:
        self._pendentes: dict = {}
        self._ultimo_fim = time.monotonic() - 60
        page.on("request", self._inicio)
        page.on("requestfinished", self._fim)
        page.on("requestfailed", self._fim)

    def _inicio(self, requisicao) -> None:
        try:
            if requisicao.resource_type in ("xhr", "fetch"):
                self._pendentes[requisicao] = time.monotonic()
        except Exception:  # noqa: BLE001, S110 — rastrear nunca derruba a página
            pass

    def _fim(self, requisicao) -> None:
        if self._pendentes.pop(requisicao, None) is not None:
            self._ultimo_fim = time.monotonic()

    def ocupada(self) -> bool:
        agora = time.monotonic()
        if any(agora - inicio < self.JANELA_S for inicio in self._pendentes.values()):
            return True
        return agora - self._ultimo_fim < self.SOSSEGO_S


def instalar_rastreador(page) -> RastreadorRede:
    """Liga o rastreador na página (uma vez). Chamado na abertura da sessão."""
    rastreador = getattr(page, "_rastreador_vp", None)
    if rastreador is None:
        rastreador = RastreadorRede(page)
        try:
            page._rastreador_vp = rastreador
        except Exception:  # noqa: BLE001, S110 — sem atributo, só não reaproveita
            pass
    return rastreador


def _pausa_na_pagina(page, ms: int) -> None:
    """Espera DEIXANDO o patchright processar eventos (o rastreador de rede só
    recebe as respostas quando a API sync é chamada; time.sleep os seguraria)."""
    try:
        page.wait_for_timeout(ms)
    except Exception as e:
        if navegador_fechou(e):
            raise
        time.sleep(ms / 1000)


def aguardar_pagina_pronta(page, timeout_ms: int = ESPERA_CARREGAMENTO_MS) -> None:
    """Espera o PERDCOMP-WEB terminar o que está fazendo: nenhum indicador de
    carregamento na tela E nenhuma requisição ao servidor pendente — e mais uma
    folga curta. Depois de `timeout_ms`, segue (com aviso)."""
    rastreador = getattr(page, "_rastreador_vp", None)
    limite = time.monotonic() + timeout_ms / 1000
    avisou = False
    while True:
        carregando = pagina_carregando(page)
        rede = rastreador is not None and rastreador.ocupada()
        if not carregando and not rede:
            break
        if not avisou:
            motivo = "carregando" if carregando else "aguardando resposta do servidor"
            print(f"       -> pagina {motivo}; aguardando terminar...")
            avisou = True
        if time.monotonic() >= limite:
            print(f"  -> [AVISO] A pagina continuou ocupada por {timeout_ms // 1000}s; seguindo.")
            break
        _pausa_na_pagina(page, 250)
    _pausa_na_pagina(page, FOLGA_ESTAVEL_MS)


# O campo foi ACEITO pelo formulário da página? O Angular marca `ng-invalid` no
# controle (o elemento com formcontrolname — no p-inputmask/p-datepicker é o
# componente em volta do <input>) enquanto o valor não foi registrado/validado.
_JS_REGISTRADO = """(el) => {
    let n = el;
    for (let i = 0; i < 5 && n; i++, n = n.parentElement) {
        if (n.hasAttribute && n.hasAttribute('formcontrolname'))
            return !n.classList.contains('ng-invalid');
    }
    return !el.classList.contains('ng-invalid');
}"""


def campo_registrado(alvo) -> bool:
    try:
        return bool(alvo.evaluate(_JS_REGISTRADO))
    except Exception as e:
        if navegador_fechou(e):
            raise
        return False


@dataclass
class Conferencia:
    """Um dado informado numa tela: como conferir e como refazer."""

    rotulo: str
    confere: Callable[[], bool]
    refaz: Callable[[], None]


def _visivel_ou_none(page, seletor: str):
    return _primeiro_visivel(_frame(page).locator(seletor))


def conf_select(page, seletor: str, texto: str, rotulo: str) -> Conferencia:
    def confere():
        alvo = _visivel_ou_none(page, seletor)
        return alvo is not None and select_confere(alvo, texto) and campo_registrado(alvo)
    return Conferencia(rotulo, confere, lambda: selecionar(page, seletor, texto, rotulo))


def conf_texto(page, seletor: str, valor: str, rotulo: str) -> Conferencia:
    def confere():
        alvo = _visivel_ou_none(page, seletor)
        return (alvo is not None and _normalizar_espacos(_ler_input(alvo)) == _normalizar_espacos(valor)
                and campo_registrado(alvo))
    return Conferencia(rotulo, confere, lambda: preencher_texto_confirmado(page, seletor, valor, rotulo))


def conf_valor(page, seletor: str, valor: str, rotulo: str) -> Conferencia:
    esperado = valor_monetario(valor)

    def confere():
        alvo = _visivel_ou_none(page, seletor)
        return (alvo is not None and valor_monetario(_ler_input(alvo)) == esperado
                and campo_registrado(alvo))
    return Conferencia(rotulo, confere, lambda: preencher_valor_confirmado(page, seletor, valor, rotulo))


def conf_digitos(page, seletor: str, texto: str, rotulo: str, formatado: str = "") -> Conferencia:
    esperado = _so_digitos(texto)

    def confere():
        alvo = _visivel_ou_none(page, seletor)
        return (alvo is not None and _so_digitos(_ler_input(alvo)) == esperado
                and campo_registrado(alvo))
    return Conferencia(rotulo, confere,
                       lambda: preencher_digitando(page, seletor, texto, rotulo, formatado=formatado))


def conf_checkbox(page, seletor: str, rotulo: str) -> Conferencia:
    def confere():
        alvo = _visivel_ou_none(page, seletor)
        try:
            return alvo is not None and bool(alvo.evaluate("(el) => el.checked")) and campo_registrado(alvo)
        except Exception as e:
            if navegador_fechou(e):
                raise
            return False
    return Conferencia(rotulo, confere, lambda: marcar_checkbox_confirmado(page, seletor, rotulo))


def conf_radio(page, localizar, seletor_input: str, rotulo: str, refaz) -> Conferencia:
    """`localizar()` devolve o rótulo VISÍVEL da opção (ou None)."""
    def confere():
        alvo = localizar()
        return alvo is not None and _marcada(alvo, seletor_input)
    return Conferencia(rotulo, confere, refaz)


TENTATIVAS_CONFERENCIA = 3


def conferir_antes_de_avancar(page, conferencias, descricao: str, diagnostico=None) -> None:
    """Página parada + todos os dados da tela registrados; o que não estiver é
    refeito (até TENTATIVAS_CONFERENCIA voltas). Levanta CampoNaoConfirmado."""
    pendentes: list[str] = []
    for volta in range(1, TENTATIVAS_CONFERENCIA + 1):
        aguardar_pagina_pronta(page)
        pendentes = [c.rotulo for c in conferencias if not c.confere()]
        if not pendentes:
            if conferencias:
                print(f"  -> Conferido antes de avancar ({descricao}): "
                      f"{len(conferencias)} dado(s) registrado(s).")
            return
        print(f"  -> [revisao] Antes de avancar ({descricao}), nao registrado(s): "
              f"{', '.join(pendentes)} (volta {volta}/{TENTATIVAS_CONFERENCIA}). Refazendo...")
        for conferencia in conferencias:
            if conferencia.rotulo in pendentes:
                conferencia.refaz()
    if diagnostico is not None:
        diagnostico("dados_nao_registrados")
    raise CampoNaoConfirmado(f"Antes de avancar ({descricao}): a pagina nao registrou "
                             + ", ".join(pendentes))


def avancar(page, clicar, aguardar, descricao: str, *, conferencias=(), diagnostico=None,
            rotulo_diagnostico="", parar_se=None) -> str:
    """Confere a tela (`conferencias`), executa `clicar()` e espera um dos
    seletores `aguardar` aparecer.

    Devolve o seletor que apareceu. Se nada aparecer em ESPERA_AVANCO_MS,
    salva a tela e levanta ProsseguirNaoAvancou com a mensagem do painel do
    PERDCOMP-WEB (erro de validação), se houver."""
    conferir_antes_de_avancar(page, list(conferencias), descricao, diagnostico)
    clicar()
    apareceu = esperar_algum(page, aguardar, ESPERA_AVANCO_MS, parar_se=parar_se)
    if apareceu:
        return apareceu
    if parar_se is not None and parar_se():
        return ""
    mensagens = mensagens_da_tela(page)
    if diagnostico is not None:
        diagnostico(rotulo_diagnostico or "nao_avancou")
    raise ProsseguirNaoAvancou(
        f"Depois de {descricao} a tela nao avancou"
        + (f": {mensagens}" if mensagens else " (sem mensagem visivel).")
    )


def prosseguir_ate(page, aguardar, descricao: str, *, conferencias=(), diagnostico=None,
                   timeout: int = 20_000, parar_se=None) -> str:
    """Confere a tela, "Prosseguir" e espera a próxima (um dos seletores `aguardar`)."""
    def _clicar():
        clicar_prosseguir(page, timeout)
        print(f"  -> 'Prosseguir' clicado ({descricao}).")
    return avancar(page, _clicar, aguardar, f"'Prosseguir' ({descricao})", conferencias=conferencias,
                   diagnostico=diagnostico, rotulo_diagnostico="prosseguir_nao_avancou",
                   parar_se=parar_se)


def etapa_ativa(page) -> str:
    """A etapa marcada no topo do formulário ("Informar Crédito", "Verificar
    Pendências"...): `ul.circular-steps p.active` (HTML real, 18/11/2026)."""
    alvo = _primeiro_visivel(_frame(page).locator("ul.circular-steps p.active"))
    return _texto_normalizado(alvo) if alvo is not None else ""


def localizar_nao_retificadora(page):
    return _primeiro_visivel(_frame(page).locator(f"label:has({SELETOR_INPUT_RETIFICADORA})").filter(
        has_text=re.compile(r"^\s*Não\s*$")))


def conferencias_identificacao(page, *, tributo: str, perdcomp: str) -> list[Conferencia]:
    """Tudo o que a identificação informou — conferido antes do "Prosseguir"."""
    return [
        conf_radio(page, lambda: _primeiro_visivel(_frame(page).locator(SELETOR_OPCAO_DCOMP)),
                   "input[name='tipoDocumento']", "Declaracao de Compensacao",
                   lambda: selecionar_declaracao_compensacao(page)),
        conf_radio(page, lambda: localizar_nao_retificadora(page), SELETOR_INPUT_RETIFICADORA,
                   "Documento Retificador = Nao", lambda: responder_retificadora_nao(page)),
        conf_select(page, SELETOR_TIPO_CREDITO, TEXTO_TIPO_CREDITO[tributo], "Tipo de Credito"),
        conf_texto(page, SELETOR_APELIDO, APELIDO_DOCUMENTO, "Apelido"),
        conf_select(page, SELETOR_QUALIFICACAO, TEXTO_QUALIFICACAO, "Qualificacao do Contribuinte"),
        conf_select(page, SELETOR_DETALHAMENTO, TEXTO_DETALHAMENTO, "Detalhamento do Credito"),
        conf_digitos(page, SELETOR_PERDCOMP_ANTERIOR, perdcomp, "PER/DCOMP anterior",
                     formatado=formatar_perdcomp(perdcomp)),
    ]


def preencher_identificacao(page, *, tributo: str, perdcomp: str, timeout: int = 30_000,
                            diagnostico=None) -> None:
    """Do "Novo Documento" até o número do PER/DCOMP anterior preenchido (passos
    enviados pelo usuário em 18/11/2026). O "Prosseguir" desta tela fica com
    `etapas_dcomp`, que sabe o que vem depois. `tributo`: "PIS", "COFINS" ou
    "PAGAMENTO INDEVIDO" (planilha.tipo_credito);
    `perdcomp`: 24 dígitos (coluna M)."""
    if tributo not in TEXTO_TIPO_CREDITO:
        raise ValueError(f"tributo fora do escopo: {tributo!r}")

    print("FASE: Novo Documento")
    abrir_novo_documento(page, timeout)

    print(f"FASE: Tipo de documento -> {TEXTO_DECLARACAO_COMPENSACAO}")
    selecionar_declaracao_compensacao(page, timeout, diagnostico)

    print("FASE: Documento Retificador? -> Nao")
    responder_retificadora_nao(page, timeout, diagnostico)

    print(f"FASE: Tipo de Credito -> {tributo}")
    selecionar(page, SELETOR_TIPO_CREDITO, TEXTO_TIPO_CREDITO[tributo], "Tipo de Credito", timeout)
    preencher_texto_confirmado(page, SELETOR_APELIDO, APELIDO_DOCUMENTO, "Apelido", timeout=timeout)
    selecionar(page, SELETOR_QUALIFICACAO, TEXTO_QUALIFICACAO, "Qualificacao do Contribuinte", timeout)

    print("FASE: Detalhamento do Credito -> PER/DCOMP anterior")
    selecionar(page, SELETOR_DETALHAMENTO, TEXTO_DETALHAMENTO, "Detalhamento do Credito", timeout)
    preencher_perdcomp_anterior(page, perdcomp, timeout)


def responder_retificadora_nao(page, timeout: int = 20_000, diagnostico=None) -> None:
    limite = time.monotonic() + timeout / 1000
    alvo = localizar_nao_retificadora(page)
    while alvo is None and time.monotonic() < limite:
        time.sleep(0.25)
        alvo = localizar_nao_retificadora(page)
    if alvo is None:
        raise CampoNaoEncontrado("A opcao 'Nao' de 'Documento Retificador?' nao apareceu.")
    clicar_radio_confirmado(
        alvo, seletor_input=SELETOR_INPUT_RETIFICADORA,
        reagiu=lambda: _visivel(page, SELETOR_TIPO_CREDITO),
        nome="Documento Retificador? = Nao", proximo="'Tipo de Credito'",
        diagnostico=diagnostico, rotulo_diagnostico="retificadora",
    )

