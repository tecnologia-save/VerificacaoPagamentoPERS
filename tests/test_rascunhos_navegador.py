"""Exclusão dos rascunhos DA AUTOMAÇÃO contra um Chrome de verdade.

Réplica da tela "Visualizar Documentos" -> "Rascunhos" mapeada no e-CAC em
21/11/2026 (debug_telas/visualizar_documentos_*): 5 rascunhos por página, uma
linha `div[sc-header]` por rascunho, apelido em `div.gs-col6`, lixeira
`i.icon-trash`, confirmação "Sim" (#botaoConfirmarExclusao) / "Não". A lista
é refeita a cada exclusão (o próximo rascunho sobe para a 1ª página).
"""
from __future__ import annotations

import html
import json

import pytest

from VerificacaoPagamento import config as _config
from VerificacaoPagamento import formulario_perdcomp as fp
from VerificacaoPagamento import rascunhos as rc

NOSSO = "Verificação Pagamento PER"

_HTML = """<!doctype html><html><head><style>
  i.iconeAcao {display:inline-block; width:16px; height:16px; background:#c60}
</style></head><body>
<nav><a><i class="icon-NovoDocumento">Novo</i></a>
     <a id="visualizar"><i class="icon-VisualizarDocumento">Visualizar</i></a></nav>
<div id="tela"></div>
<div id="modal" style="display:none">Deseja confirmar a exclusão do Rascunho <b id="nome"></b>?
  <button id="botaoConfirmarExclusao" type="button">Sim</button>
  <button id="botaoCancelarExclusao" type="button">Não</button></div>
<script>
  const rascunhos = __RASCUNHOS__;
  const excluidos = [];
  let alvo = -1;
  function desenhar() {
    const linhas = rascunhos.slice(0, 5).map((r, i) =>
      `<simple-collapsible><div sc-header="" class="gs-row"><div class="gs-col2">21/11/2026</div>`
      + `<div class="gs-col6 sc-clickable wrapword"> ${r} </div>`
      + `<div class="gs-col1"><i class="icon-button icon-pencil iconeAcao"></i></div>`
      + `<div class="gs-col1"><span><i class="icon-button icon-trash iconeAcao" data-i="${i}"></i></span></div>`
      + `</div></simple-collapsible>`).join("");
    document.getElementById("tela").innerHTML =
      `<p class="title">Rascunhos</p><perdcomp-listar-docs-nao-enviados><div>${linhas}</div>`
      + `</perdcomp-listar-docs-nao-enviados>`;
  }
  document.querySelector(".icon-VisualizarDocumento").addEventListener("click", () =>
    setTimeout(desenhar, 300));
  document.getElementById("tela").addEventListener("click", (ev) => {
    const i = ev.target.dataset.i;
    if (i === undefined) return;
    alvo = Number(i);
    document.getElementById("nome").textContent = rascunhos[alvo];
    document.getElementById("modal").style.display = "block";
  });
  document.getElementById("botaoConfirmarExclusao").addEventListener("click", () => {
    document.getElementById("modal").style.display = "none";
    excluidos.push(rascunhos.splice(alvo, 1)[0]);
    document.body.dataset.excluidos = JSON.stringify(excluidos);
    document.body.dataset.restantes = JSON.stringify(rascunhos);
    setTimeout(desenhar, 400);
  });
  document.getElementById("botaoCancelarExclusao").addEventListener("click", () =>
    document.getElementById("modal").style.display = "none");
</script></body></html>"""


@pytest.fixture
def abrir(navegador):
    paginas = []

    def _abrir(rascunhos):
        page = navegador.new_page(viewport={"width": 1200, "height": 800})
        paginas.append(page)
        app = _HTML.replace("__RASCUNHOS__", json.dumps(rascunhos, ensure_ascii=False))
        page.set_content(f'<html><body style="margin:0"><iframe id="frmApp" '
                         f'style="width:1180px;height:780px;border:0" '
                         f'srcdoc="{html.escape(app, quote=True)}"></iframe></body></html>')
        page.frame_locator("#frmApp").locator("#visualizar").wait_for(state="attached")
        return page

    yield _abrir
    for page in paginas:
        page.close()


@pytest.fixture(autouse=True)
def _rapido(monkeypatch):
    monkeypatch.setattr(fp, "FOLGA_ESTAVEL_MS", 50)


def _estado(page) -> tuple[list[str], list[str] | None]:
    frame = next(f for f in page.frames if f != page.main_frame)
    dados = frame.evaluate("() => ({...document.body.dataset})")
    return json.loads(dados.get("excluidos", "[]")), (
        json.loads(dados["restantes"]) if "restantes" in dados else None)


def test_exclui_10_os_da_automacao_primeiro_depois_quaisquer(abrir):
    """Regra do usuário (21/11/2026): 10 por vez, mesmo que não sejam nossos."""
    outros = [f"Outro {i}" for i in range(8)]
    # 12 rascunhos: 4 nossos (2 só na 2ª página) entre 8 de outra origem.
    page = abrir([outros[0], NOSSO, outros[1], NOSSO, outros[2], outros[3], NOSSO,
                  outros[4], outros[5], NOSSO, outros[6], outros[7]])
    assert rc.excluir_rascunhos(page) == 10
    excluidos, restantes = _estado(page)
    # os 4 nossos saíram (os da 2ª página quando subiram), e 6 dos outros
    assert sorted(excluidos) == sorted([NOSSO] * 4 + outros[:6])
    assert restantes == outros[6:]


def test_rascunhos_iguais_um_atras_do_outro(abrir):
    """Mesmo apelido e mesma data: a lista refeita parece igual — a exclusão
    é conferida pela linha marcada, não pelo texto."""
    page = abrir([NOSSO] * 7)
    assert rc.excluir_rascunhos(page, maximo=3) == 3
    assert _estado(page)[1] == [NOSSO] * 4


def test_lista_vazia_nao_exclui_nada(abrir):
    page = abrir([])
    assert rc.excluir_rascunhos(page) == 0
    assert _estado(page) == ([], None)


def test_modo_seguro_nao_exclui(abrir, monkeypatch):
    monkeypatch.setattr(_config, "PERMITIR_ACOES_REAIS_NO_ECAC", False)
    page = abrir([NOSSO])
    with pytest.raises(rc.ExclusaoNaoPermitida):
        rc.excluir_rascunhos(page)
    assert _estado(page) == ([], None)
