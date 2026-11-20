"""A tela de identificação da Declaração de Compensação contra um Chrome DE VERDADE.

A página é uma réplica da tela real: os radios de tipo (HTML capturado na
Restituição, debug_telas/check_fase3_*_frame1) e os campos seguintes com o
HTML enviado pelo usuário em 18/11/2026 — Retificador Sim/Não, selects com
value "N: Object", apelido, e o p-inputmask do PER/DCOMP anterior, que
formata enquanto se digita. Tudo dentro do iframe #frmApp, com o formulário
reativo revelando os campos na ordem.

Cenários do tipo de documento reproduzem dificuldades já vistas nas irmãs:
overlay do PrimeNG interceptando o clique, tela antiga escondida no DOM,
clique duplo (a contagem é conferida) e data-value renumerado.

Os marcadores ficam no DOM (document.body.dataset), e não em window.*: o
patchright avalia JS num mundo isolado, que vê o DOM mas não as variáveis da
página. Pula se o Chrome não abrir nesta máquina.
"""
from __future__ import annotations

import html

import pytest

from VerificacaoPagamento import formulario_perdcomp as fp

PERDCOMP = "137161286723012411189229"
PERDCOMP_FORMATADO = "13716.12867.230124.1.1.18-9229"

OPCOES_REAIS = [
    ("3", "Declaração de Compensação"),
    ("2", "Pedido de Restituição"),
    ("1", "Pedido de Ressarcimento"),
    ("4", "Pedido de Reembolso"),
    ("5", "Pedido de Cancelamento"),
]
TIPOS_CREDITO = [
    "Cofins Não-Cumulativa - Ressarcimento/Compensação - PA a partir de Janeiro de 2014",
    "Contribuição Previdenciária Indevida ou a Maior",
    "Pagamento Indevido ou a Maior",
    "PIS/PASEP Não-Cumulativo - Ressarcimento/Compensação - PA a partir de Janeiro de 2014",
    "Saldo Negativo de IRPJ",
]


def _radios(opcoes):
    itens = "".join(
        '<div class="col-xs-05 itemAtivo"><label class="radio-inline">'
        '<input type="radio" id="tipoDocumento" name="tipoDocumento">'
        f'<span><i aria-hidden="true" class="icon-radio" data-value="{dv}"></i> {texto}<br></span>'
        "</label></div>"
        for dv, texto in opcoes
    )
    return f'<div class="row ecac">{itens}</div>'


def _select(id_, controle, opcoes):
    itens = "".join(f'<option value="{i}: Object"> {t} </option>' for i, t in enumerate(opcoes, 1))
    return (f'<select formcontrolname="{controle}" id="{id_}" class="form-control">'
            f'<option value="">Selecione...</option>{itens}</select>')


def _retificadora():
    radio = ('<input type="radio" formcontrolname="tipoRetificadora" id="tipoRetificadora" '
             'name="tipoRetificadora"><div class="control__indicator"></div>')
    return ('<div class="form-group"><label for="tipoRetificadora">Documento Retificador?*</label>'
            f'<label class="control control--radio">Sim {radio}</label>'
            f'<label class="control control--radio">Não {radio}</label></div>')


def _app(*, opcoes=OPCOES_REAIS, overlay_ms=None, reage=True, tela_antiga=False,
         formulario_visivel=False, prosseguir_aceita=True) -> str:
    """HTML do iframe. overlay_ms: None = sem overlay; N = some depois de N ms;
    -1 = nunca sai. `formulario_visivel`: a pergunta do tipo já na tela (sem
    precisar de "Novo Documento")."""
    antiga = (f'<div id="antiga" style="display:none">{_radios(opcoes)}</div>'
              if tela_antiga else "")
    overlay = '<div class="ui-widget-overlay"></div>' if overlay_ms is not None else ""
    estilo_form = "" if formulario_visivel else ' style="display:none"'
    escondido = ' style="display:none"'
    return f"""<!doctype html><html><head><style>
      .ui-widget-overlay {{position:fixed;top:0;left:0;width:100%;height:100%;
                           background:rgba(0,0,0,.4);z-index:1000}}
    </style></head><body>
    <nav><a><i class="icon-NovoDocumento">Novo<br>Documento</i></a></nav>
    {antiga}
    <form id="novo"{estilo_form}>
      <label for="tipoDocumento">Que documento deseja criar?</label>
      <div class="container-fluid">{_radios(opcoes)}</div>
      <div id="perguntas"{escondido}>{_retificadora()}</div>
      <div id="campos"{escondido}>
        {_select("tipoCredito", "tipoCredito", TIPOS_CREDITO)}
        <input id="apelidoDocumento" type="text" maxlength="80" formcontrolname="nomeRascunho">
        {_select("qualificacaoContribuinte", "qualificacaoContribuinte",
                 ["Outra Qualificação", "Sociedade Cooperativa Agropecuária ou de Consumo"])}
        {_select("tipoIdentificacaoCredito", "tipoIdentificacaoCredito",
                 ["O crédito será detalhado neste documento",
                  "O crédito já foi detalhado em PER/DCOMP anterior",
                  "O crédito já foi detalhado em Processo Administrativo"])}
        <div id="campo-perdcomp"{escondido}>
          <input pinputtext="" class="p-inputtext p-component form-control p-inputmask"
                 type="text" placeholder="99999.99999.999999.9.9.99-9999">
        </div>
      </div>
      <perdcomp-painel-mensagens><div id="msgs"></div></perdcomp-painel-mensagens>
    </form>
    <div id="tela-seguinte"{escondido}>Identificação do Crédito</div>
    <perdcomp-barra-botoes><button name="btnProsseguir" type="button">Prosseguir</button></perdcomp-barra-botoes>
    {overlay}
    <script>
      const marca = document.body.dataset;
      marca.cliques = '0';
      const mostrar = (id) => document.getElementById(id).style.display = '';
      document.querySelectorAll('#novo input[name=tipoDocumento]').forEach(inp =>
        inp.addEventListener('click', () => {{
          marca.cliques = String(Number(marca.cliques) + 1);
          marca.escolhido = inp.parentElement.querySelector('i').dataset.value;
          if ({str(reage).lower()}) setTimeout(() => mostrar('perguntas'), 150);
        }}));
      document.querySelectorAll('#antiga input').forEach(inp =>
        inp.addEventListener('click', () => {{ marca.escolhido = 'TELA ANTIGA'; }}));
      document.querySelectorAll('#perguntas input').forEach(inp =>
        inp.addEventListener('click', () => {{
          marca.retificadora = inp.parentElement.textContent.trim();
          if (marca.retificadora === 'Não') setTimeout(() => mostrar('campos'), 150);
        }}));
      document.getElementById('tipoIdentificacaoCredito').addEventListener('change', (e) => {{
        document.getElementById('campo-perdcomp').style.display = e.target.value === '2: Object' ? '' : 'none';
      }});
      // p-inputmask simplificado: só dígitos, pontuação montada na hora.
      const mascara = document.querySelector('.p-inputmask');
      mascara.addEventListener('input', () => {{
        const d = mascara.value.replace(/\\D/g, '').slice(0, 24);
        const cortes = [[0,5,''],[5,10,'.'],[10,16,'.'],[16,17,'.'],[17,18,'.'],[18,20,'.'],[20,24,'-']];
        let s = '';
        for (const [a, b, sep] of cortes) {{ if (d.length > a) s += sep + d.slice(a, b); }}
        mascara.value = s;
      }});
      document.querySelector('.icon-NovoDocumento').addEventListener('click', () => mostrar('novo'));
      document.querySelector('[name=btnProsseguir]').addEventListener('click', () => {{
        const txt = (id) => {{ const s = document.getElementById(id); return s.options[s.selectedIndex].textContent.trim(); }};
        marca.tipoCredito = txt('tipoCredito');
        marca.apelido = document.getElementById('apelidoDocumento').value;
        marca.qualificacao = txt('qualificacaoContribuinte');
        marca.detalhamento = txt('tipoIdentificacaoCredito');
        marca.perdcomp = mascara.value;
        if ({str(prosseguir_aceita).lower()} && mascara.value.replace(/\\D/g, '').length === 24) {{
          document.getElementById('novo').style.display = 'none';
          mostrar('tela-seguinte');
        }} else {{
          document.getElementById('msgs').textContent = 'Campo obrigatório não preenchido.';
        }}
      }});
      const ov = document.querySelector('.ui-widget-overlay');
      if (ov && {overlay_ms if overlay_ms is not None else -1} > 0)
        setTimeout(() => ov.remove(), {overlay_ms if overlay_ms is not None else 0});
    </script></body></html>"""


@pytest.fixture
def abrir(navegador):
    paginas = []

    def _abrir(**kwargs):
        page = navegador.new_page(viewport={"width": 1200, "height": 800})
        paginas.append(page)
        srcdoc = html.escape(_app(**kwargs), quote=True)
        page.set_content(f'<html><body style="margin:0"><iframe id="frmApp" '
                         f'style="width:1180px;height:780px;border:0" srcdoc="{srcdoc}"></iframe>'
                         "</body></html>")
        page.frame_locator("#frmApp").locator("#novo").wait_for(state="attached")
        return page

    yield _abrir
    for page in paginas:
        page.close()


def _estado(page) -> dict:
    frame = next(f for f in page.frames if f != page.main_frame)
    dados = frame.evaluate("() => ({...document.body.dataset})")
    dados["cliques"] = int(dados.get("cliques", 0))
    return dados


@pytest.fixture
def rapido(monkeypatch):
    """Prazos curtos para os cenários que esperam estourar."""
    monkeypatch.setattr(fp, "ESPERA_BLOQUEIO_MS", 1_000)
    monkeypatch.setattr(fp, "TIMEOUT_CLIQUE_MS", 1_500)
    monkeypatch.setattr(fp, "ESPERA_REACAO_MS", 1_500)
    monkeypatch.setattr(fp, "ESPERA_AVANCO_MS", 1_500)


# ── Tipo de documento ────────────────────────────────────────────────────────

def test_seleciona_com_um_unico_clique(abrir):
    page = abrir(formulario_visivel=True)
    fp.selecionar_declaracao_compensacao(page, timeout=5_000)
    estado = _estado(page)
    assert (estado["cliques"], estado["escolhido"]) == (1, "3")


def test_espera_o_overlay_sair_e_clica_uma_vez(abrir):
    """O erro real da Restituição: '.ui-widget-overlay intercepts pointer events'."""
    page = abrir(formulario_visivel=True, overlay_ms=1_500)
    fp.selecionar_declaracao_compensacao(page, timeout=5_000)
    estado = _estado(page)
    assert (estado["cliques"], estado["escolhido"]) == (1, "3")


def test_overlay_que_nao_sai_cai_para_o_clique_via_js(abrir, rapido):
    page = abrir(formulario_visivel=True, overlay_ms=-1)
    fp.selecionar_declaracao_compensacao(page, timeout=5_000)
    estado = _estado(page)
    assert estado["escolhido"] == "3"
    assert estado["cliques"] == 1  # o clique de verdade foi barrado; só o JS chegou


def test_ignora_a_tela_antiga_escondida_no_dom(abrir):
    page = abrir(formulario_visivel=True, tela_antiga=True)
    fp.selecionar_declaracao_compensacao(page, timeout=5_000)
    estado = _estado(page)
    assert (estado["cliques"], estado["escolhido"]) == (1, "3")


def test_data_value_renumerado_escolhe_pelo_texto(abrir):
    renumeradas = [("9", "Declaração de Compensação"), ("2", "Pedido de Restituição"),
                   ("1", "Pedido de Ressarcimento"), ("3", "Pedido de Reembolso"),
                   ("5", "Pedido de Cancelamento")]
    page = abrir(formulario_visivel=True, opcoes=renumeradas)
    fp.selecionar_declaracao_compensacao(page, timeout=5_000)
    assert _estado(page)["escolhido"] == "9"  # e NÃO o Reembolso, que ficou com o 3


def test_marcada_sem_o_retificador_aparecer_e_erro(abrir, rapido):
    """O Retificador SEMPRE aparece depois da Declaração (confirmado ao vivo):
    sem ele, a seleção não valeu — erro, com a tela salva."""
    page = abrir(formulario_visivel=True, reage=False)
    retratos = []
    with pytest.raises(fp.TipoDocumentoNaoSelecionado):
        fp.selecionar_declaracao_compensacao(page, timeout=5_000, diagnostico=retratos.append)
    assert _estado(page)["escolhido"] == "3"
    assert "dcomp_marcada_sem_reacao" in retratos


def test_ja_selecionada_nao_clica_de_novo(abrir):
    page = abrir(formulario_visivel=True)
    fp.selecionar_declaracao_compensacao(page, timeout=5_000)
    fp.selecionar_declaracao_compensacao(page, timeout=5_000)
    assert _estado(page)["cliques"] == 1


def test_sem_a_opcao_na_tela_levanta(abrir, rapido):
    page = abrir(formulario_visivel=True, opcoes=[("2", "Pedido de Restituição")])
    with pytest.raises(fp.TipoDocumentoNaoSelecionado):
        fp.selecionar_declaracao_compensacao(page, timeout=1_000)


# ── Identificação completa (Novo Documento -> Prosseguir) ────────────────────

@pytest.mark.parametrize(("tributo", "texto"), [
    ("PIS", "PIS/PASEP Não-Cumulativo - Ressarcimento/Compensação - PA a partir de Janeiro de 2014"),
    ("COFINS", "Cofins Não-Cumulativa - Ressarcimento/Compensação - PA a partir de Janeiro de 2014"),
    ("PAGAMENTO INDEVIDO", "Pagamento Indevido ou a Maior"),     # código 04 / INSS... (20/11/2026)
])
def test_preenche_a_identificacao_e_prossegue(abrir, tributo, texto):
    page = abrir()
    fp.preencher_identificacao(page, tributo=tributo, perdcomp=PERDCOMP, timeout=5_000)
    assert fp.prosseguir_ate(page, ("#tela-seguinte",), "identificacao") == "#tela-seguinte"
    estado = _estado(page)
    assert (estado["cliques"], estado["escolhido"], estado["retificadora"]) == (1, "3", "Não")
    assert estado["tipoCredito"] == texto
    assert estado["apelido"] == "Verificação Pagamento PER"
    assert estado["qualificacao"] == "Outra Qualificação"
    assert estado["detalhamento"] == "O crédito já foi detalhado em PER/DCOMP anterior"
    assert estado["perdcomp"] == PERDCOMP_FORMATADO


def test_prosseguir_que_nao_avanca_levanta_com_a_mensagem_da_tela(abrir, rapido):
    page = abrir(prosseguir_aceita=False)
    retratos = []
    fp.preencher_identificacao(page, tributo="PIS", perdcomp=PERDCOMP, timeout=5_000)
    with pytest.raises(fp.ProsseguirNaoAvancou, match="Campo obrigatório"):
        fp.prosseguir_ate(page, ("#tela-seguinte",), "identificacao", diagnostico=retratos.append)
    assert retratos == ["prosseguir_nao_avancou"]


def test_formatar_perdcomp():
    assert fp.formatar_perdcomp(PERDCOMP) == PERDCOMP_FORMATADO
    with pytest.raises(ValueError):
        fp.formatar_perdcomp("123")
