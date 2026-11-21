"""Excluir rascunhos quando o PER/DCOMP diz "Excedido o número de rascunhos
permitidos pelo sistema".

REGRA DO USUÁRIO (21/11/2026): os rascunhos não são importantes — "apague 10
rascunhos por vez, mesmo que não sejam nossos". Exclui até MAX_EXCLUSOES
(10); os da automação (apelido APELIDO_DOCUMENTO) saem primeiro, depois
quaisquer outros.

Caminho (o mesmo da Protocolação Previdenciária, tela mapeada em 21/11/2026,
debug_telas/visualizar_documentos_*): barra lateral "Visualizar Documentos"
(i.icon-VisualizarDocumento) -> aba "Rascunhos" (a que abre) -> lista
`perdcomp-listar-docs-nao-enviados`, 5 por página, uma linha `div[sc-header]`
por rascunho com o apelido em `div.gs-col6` e a lixeira `i.icon-trash` ->
"Deseja confirmar a exclusão do Rascunho <apelido>?" -> "Sim"
(#botaoConfirmarExclusao). A cada exclusão a lista é refeita e traz o
próximo rascunho para a 1ª página.
"""
from __future__ import annotations

from . import config as _config
from .config import APELIDO_DOCUMENTO, FRAME_PERDCOMP
from .formulario_perdcomp import aguardar_pagina_pronta

SELETOR_NAV_VISUALIZAR = "i.icon-VisualizarDocumento"
SELETOR_LISTA_RASCUNHOS = "perdcomp-listar-docs-nao-enviados"
SELETOR_LINHA = "perdcomp-listar-docs-nao-enviados div[sc-header]"
SELETOR_APELIDO = "div.gs-col6"
SELETOR_LIXEIRA = "i.icon-trash"
SELETOR_CONFIRMAR = "#botaoConfirmarExclusao"
MAX_EXCLUSOES = 10


def normalizar_espacos(texto: str) -> str:
    return " ".join((texto or "").split())


class ExclusaoNaoPermitida(Exception):
    """Modo seguro (PERMITIR_ACOES_REAIS_NO_ECAC=False): nada é excluído."""


class ExclusaoNaoConfirmada(Exception):
    """A lixeira foi clicada mas o rascunho continuou na lista."""


def _escolher(frame):
    """A próxima linha a excluir: uma da automação, senão a primeira. None = lista vazia."""
    alvo = normalizar_espacos(APELIDO_DOCUMENTO).casefold()
    linhas = frame.locator(SELETOR_LINHA)
    total = linhas.count()
    for i in range(total):
        linha = linhas.nth(i)
        try:
            apelido = normalizar_espacos(linha.locator(SELETOR_APELIDO).first.inner_text(timeout=3_000))
        except Exception:  # noqa: BLE001 — linha que sumiu enquanto lia
            continue
        if apelido.casefold() == alvo:
            return linha, apelido
    if not total:
        return None
    try:
        apelido = normalizar_espacos(linhas.first.locator(SELETOR_APELIDO).first.inner_text(timeout=3_000))
    except Exception:  # noqa: BLE001
        apelido = "?"
    return linhas.first, apelido


def _abrir_lista(page, timeout_ms: int = 30_000):
    frame = page.frame_locator(FRAME_PERDCOMP)
    frame.locator(SELETOR_NAV_VISUALIZAR).first.click(timeout=timeout_ms)
    # "attached": sem rascunhos o componente fica vazio (sem altura).
    frame.locator(SELETOR_LISTA_RASCUNHOS).first.wait_for(state="attached", timeout=timeout_ms)
    aguardar_pagina_pronta(page)
    return frame


def excluir_rascunhos(page, *, maximo: int = MAX_EXCLUSOES, diagnostico=None) -> int:
    """Exclui até `maximo` rascunhos (os da automação primeiro). Devolve
    quantos foram excluídos (0 = lista vazia). Em modo seguro não exclui nada
    (ExclusaoNaoPermitida). A tela fica em "Visualizar Documentos": quem chama
    recarrega o módulo antes do próximo documento."""
    if not _config.PERMITIR_ACOES_REAIS_NO_ECAC:
        raise ExclusaoNaoPermitida("modo seguro: nenhum rascunho e excluido")
    print("FASE: Visualizar Documentos -> excluir rascunhos")
    frame = _abrir_lista(page)
    excluidos = 0
    while excluidos < maximo:
        escolhido = _escolher(frame)
        if escolhido is None:
            break
        linha, apelido = escolhido
        # Marca a linha: some quando a lista for refeita sem ela.
        linha.evaluate("el => el.setAttribute('data-vp-excluir', '1')")
        linha.locator(SELETOR_LIXEIRA).first.click(timeout=15_000)
        confirmar = frame.locator(SELETOR_CONFIRMAR).first
        confirmar.wait_for(state="visible", timeout=15_000)
        if excluidos == 0 and diagnostico is not None:
            diagnostico("rascunhos_confirmar_exclusao")
        confirmar.click(timeout=15_000)
        confirmar.wait_for(state="hidden", timeout=30_000)
        aguardar_pagina_pronta(page)
        try:
            frame.locator("[data-vp-excluir]").first.wait_for(state="detached", timeout=30_000)
        except Exception as e:  # noqa: BLE001
            raise ExclusaoNaoConfirmada(
                f"o rascunho '{apelido}' continuou na lista depois de confirmar a exclusao "
                f"({excluidos} excluidos)") from e
        excluidos += 1
        print(f"  -> [RASCUNHOS] Rascunho {excluidos} excluido ('{apelido}').")
    print(f"  -> [RASCUNHOS] {excluidos} rascunho(s) excluido(s).")
    return excluidos
