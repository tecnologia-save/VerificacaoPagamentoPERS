"""Caixa Postal num Chrome de verdade, com o portal SIMULADO (rotas): o filtro
"importantes" + "não lida", a lista lida da resposta da API, a abertura pelo
link do assunto e a conferência do CNPJ. Dados FICTÍCIOS."""
from __future__ import annotations

import json

import pytest

from VerificacaoPagamento import caixa_postal as cp

CNPJ = "11222333000181"

SHELL = """<!doctype html><html><body>
<div id="informacao-perfil"><div><span>Titular (Acesso GOV.BR por Certificado): 24.245.826/0001-89 -
SAVE FICTICIA</span></div><div><span>Procurador de: __PERFIL__ - EMPRESA FICTICIA</span></div></div>
<iframe id="frmApp" src="/caixapostal/app" style="width:1000px;height:700px"></iframe>
</body></html>"""

APP = r"""<!doctype html><html><head><style>
ng-select{display:block;margin:4px;border:1px solid #999;width:400px}
.ng-option{padding:2px} [hidden]{display:none!important}</style></head><body>
<app-lista-mensagens id="lista">
  <i class="fa fa-filter" title="Filtros" onclick="document.getElementById('painel').hidden=false">F</i>
  <div id="painel" hidden>
    <ng-select data-opcoes='["Todas","Exibir apenas mensagens importantes (Bloqueiam o e-CAC)"]'>
      <div class="ng-select-container">Tipo</div><span class="ng-value-label"></span></ng-select>
    <ng-select data-opcoes='["Lida","Não lida"]'>
      <div class="ng-select-container">Situação</div><span class="ng-value-label"></span></ng-select>
    <button type="button" id="filtrar">Filtrar</button>
  </div>
  <table><tbody id="linhas"></tbody></table>
</app-lista-mensagens>
<div id="mensagem" hidden><div class="fieldset-header"><legend id="titulo"></legend></div>
  <p>Prezado contribuinte, texto da mensagem.</p><button type="button" id="voltar">Voltar</button></div>
<script>
const fechar = () => document.querySelectorAll('ng-dropdown-panel').forEach(p => p.remove());
document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') fechar(); });
document.querySelectorAll('ng-select').forEach((sel) => {
  sel.querySelector('.ng-select-container').addEventListener('click', () => {
    fechar();
    const painel = document.createElement('ng-dropdown-panel');
    JSON.parse(sel.dataset.opcoes).forEach((t) => {
      const o = document.createElement('div'); o.className = 'ng-option'; o.textContent = t;
      o.addEventListener('click', () => { sel.querySelector('.ng-value-label').textContent = t; fechar(); });
      painel.appendChild(o);
    });
    document.body.appendChild(painel);
  });
});
document.getElementById('filtrar').addEventListener('click', async () => {
  const r = await fetch('/caixapostal/api/mensagens?filtro=1');
  const dados = await r.json();
  const corpo = document.getElementById('linhas'); corpo.innerHTML = '';
  dados.mensagens.forEach((m) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><a href="/caixapostal/mensagens/${m.isn}" class="rem">Receita Federal</a></td>` +
                   `<td><a href="/caixapostal/mensagens/${m.isn}">${m.assunto}</a></td>`;
    corpo.appendChild(tr);
  });
});
document.addEventListener('click', async (ev) => {
  const a = ev.target.closest('a[href*="/mensagens/"]');
  if (!a) return;
  ev.preventDefault();
  const isn = a.getAttribute('href').split('/').pop();
  await fetch('/caixapostal/api/ler/' + isn);
  document.getElementById('titulo').innerHTML = a.textContent + '<span class="sr-only"> expandido</span>';
  document.getElementById('lista').hidden = true;
  document.getElementById('mensagem').hidden = false;
});
document.getElementById('voltar').addEventListener('click', () => {
  document.getElementById('mensagem').hidden = true;
  document.getElementById('lista').hidden = false;
});
</script></body></html>"""


@pytest.fixture
def portal(navegador):
    """(page, estado). `estado["mensagens"]`: as da caixa; abrir marca `lida`."""
    contexto = navegador.new_context()
    page = contexto.new_page()
    estado = {"perfil": "11.222.333/0001-81", "lidas_pelo_portal": [], "mensagens": [
        {"isn": 501, "assunto": "Intimação - Processo 10000.000001/2026-11", "relevante": True,
         "lida": False, "dataEnvio": "18/11/2026"},
        {"isn": 502, "assunto": "Termo de exclusão", "relevante": True, "lida": False},
        {"isn": 503, "assunto": "Comunicado comum", "relevante": False, "lida": False},
        {"isn": 504, "assunto": "Importante antiga", "relevante": True, "lida": True},
    ]}

    def rota(route):
        url = route.request.url
        if "/api/mensagens" in url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"mensagens": estado["mensagens"]}))
        elif "/api/ler/" in url:
            isn = int(url.rsplit("/", 1)[-1])
            estado["lidas_pelo_portal"].append(isn)
            for m in estado["mensagens"]:
                if m["isn"] == isn:
                    m["lida"] = True
            route.fulfill(status=200, content_type="application/json", body="{}")
        elif "/caixapostal/app" in url:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=APP)
        else:
            route.fulfill(status=200, content_type="text/html; charset=utf-8",
                          body=SHELL.replace("__PERFIL__", estado["perfil"]))

    page.route("**/*", rota)
    yield page, estado
    contexto.close()


def test_abre_so_as_importantes_nao_lidas_e_anota_cada_uma(portal):
    page, estado = portal
    anotadas = []
    total = cp.abrir_todas(page, CNPJ, ao_abrir=lambda isn, assunto: anotadas.append((isn, assunto)))
    assert total == 2
    assert anotadas == [("501", "Intimação - Processo 10000.000001/2026-11"),
                        ("502", "Termo de exclusão")]
    assert estado["lidas_pelo_portal"] == [501, 502]         # a comum e a já lida não são tocadas


def test_caixa_postal_de_outro_cnpj_nao_abre_nada(portal):
    page, estado = portal
    estado["perfil"] = "99.888.777/0001-66"
    with pytest.raises(cp.CaixaPostalNaoReconhecida, match="nada é aberto"):
        cp.abrir_todas(page, CNPJ, ao_abrir=lambda isn, assunto: None)
    assert estado["lidas_pelo_portal"] == []


def test_lista_com_o_filtro_traz_as_importantes_nao_lidas(portal):
    page, _ = portal
    assert [m.isn for m in cp.listar(page, CNPJ)] == ["501", "502"]
