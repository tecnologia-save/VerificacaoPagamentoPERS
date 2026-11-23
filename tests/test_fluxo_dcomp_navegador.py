"""A Declaração de Compensação INTEIRA contra um Chrome de verdade.

Réplica das telas com o HTML enviado pelo usuário em 18/11/2026 (termo de
inconstitucionalidade, não litígio, crédito original, Informar Débito, CPF do
responsável, Verificação de Pendências, Enviar e os dois desfechos). Um
`Prosseguir` só, que avança conforme a etapa — e só avança com a etapa
preenchida, como o formulário reativo de verdade.

Marcadores no DOM (document.body.dataset): o patchright avalia JS num mundo
isolado. Pula se o Chrome não abrir.
"""
from __future__ import annotations

import html

import pytest

from tests.test_tipo_documento_navegador import (
    OPCOES_REAIS,
    PERDCOMP,
    TIPOS_CREDITO,
    _radios,
    _retificadora,
    _select,
)
from VerificacaoPagamento import etapas_dcomp as et
from VerificacaoPagamento import formulario_perdcomp as fp
from VerificacaoPagamento.config import (
    SITUACAO_NAO_APTO,
    SITUACAO_PAGAMENTO_REALIZADO,
    SITUACAO_PROTOCOLADA,
)
from VerificacaoPagamento.desfechos import EnvioSemConfirmacao

NUMERO_ENVIADO = "34450.37448.181126.1.3.19-4627"

RECEITAS = ["0760-01 - Cofins - Regime Especial de Tributação - Cervejas",
            "2172-01 - Cofins - Faturamento/PJ em geral",
            "5856-01 - Cofins - Não cumulativa",
            "5856-08 - Cofins - Não cumulativa/SCP"]

_HTML = """<!doctype html><html><head><style>
  .oculto {display:none}
</style></head><body>
<perdcomp-painel-mensagens><div principal=""></div></perdcomp-painel-mensagens>
<nav><a><i class="icon-NovoDocumento">Novo<br>Documento</i></a></nav>
<ul class="circular-steps"><p id="etapa" class="active">Identificar Documento</p></ul>
<perdcomp-loading><div id="carregando" class="oculto">Carregando...</div></perdcomp-loading>
<form id="novo" class="oculto">
  <label for="tipoDocumento">Que documento deseja criar?</label>
  __RADIOS__
  <div id="perguntas" class="oculto">__RETIFICADORA__</div>
  <div id="campos" class="oculto">
    __TIPO_CREDITO__
    <input id="apelidoDocumento" type="text" maxlength="80">
    __QUALIFICACAO__
    __DETALHAMENTO__
    <input id="perdcompAnterior" class="p-inputmask oculto" type="text" placeholder="99999.99999.999999.9.9.99-9999">
  </div>
</form>
<div id="modal-termo" class="oculto"><div class="form-group">
  <label class="control control--radio">Sim <input type="radio" formcontrolname="termoAceito" name="termoAceito"><div class="control__indicator"></div></label>
  <label class="control control--radio">Não <input type="radio" formcontrolname="termoAceito" name="termoAceito"><div class="control__indicator"></div></label>
  </div><button id="botaoOkTermoAceito" type="button" class="botaoModal">OK</button></div>
<div id="tela-litigio" class="oculto"><label><input type="checkbox" formcontrolname="litigioProcJudicial"> O Contribuinte não está litigando em Processo Judicial ou Administrativo sobre matéria que possa alterar o valor a ser Ressarcido/Compensado</label></div>
<div id="tela-ci" class="oculto"><ul>
  <li class="tab active" id="Identificação do Crédito"><a tabindex="0">Identificação do Crédito</a></li>
  <li class="tab" id="Detalhamento do Crédito"><a tabindex="0">Detalhamento do Crédito</a></li>
  <li class="tab" id="Demonstrativo do Crédito"><a tabindex="0">Demonstrativo do Crédito</a></li></ul>
  <div id="ci-ident"><select formcontrolname="titularidade" id="detentor" disabled="true"><option>Crédito apurado pelo próprio contribuinte</option></select></div></div>
<div id="tela-credito" class="oculto"><input type="text" perdcompcurrency="" maxlength="18" formcontrolname="creditoOriginalDataEntrega" id="creditoOriginalDataEntrega"></div>
<div id="tela-debitos" class="oculto"><button name="btnIncluir" type="button">Informar Débito</button>
  <div id="form-debito" class="oculto">
    __GRUPO__
    __TIPO_DEBITO__
    <span id="receita-wrap" class="oculto">__RECEITA__</span>
    <input type="text" formcontrolname="internalValue" id="periodoApuracao" placeholder="MM/AAAA">
    <input type="text" class="p-datepicker-input" placeholder="DD/MM/AAAA" id="dataVencimento">
    <input type="text" formcontrolname="valorPrincipal" id="valorPrincipal" perdcompcurrency="" maxlength="18">
    <button type="button">Confirmar</button>
  </div></div>
<div id="tela-responsavel" class="oculto"><input class="p-inputmask" type="text" placeholder="999.999.999-99"></div>
<div id="tela-pendencias" class="oculto"><div id="apto" class="info oculto"><i class="icon-ok_sign info"></i>O Documento está apto para envio </div></div>
<div id="tela-envio" class="oculto"><button name="btnEnviar" type="button" perdcompdisablewhenprocessing="">Enviar</button></div>
<div id="popup-pendencias" class="oculto"><p>O documento examinado apresenta pendências que não impedem seu envio à RFB. Deseja verificá-las?</p>
  <button id="botaoSimVerificarPendenciasNaoImpeditivas" type="button">Sim</button>
  <button id="botaoNaoVerificarPendenciasNaoImpeditivas" type="button">Não</button></div>
<div id="popup-enviado" class="oculto"><p>Declaração foi enviada com sucesso.<br>Número do Documento: <strong>__NUMERO__</strong></p>
  <button id="botaoNavegarTelaInicial" type="button" class="botaoModal">OK</button></div>
<perdcomp-painel-mensagens><div principal=""><div id="alerta" class="alert2 painel-mensagens oculto">
  <div class="alert-message"><p id="msgs"></p></div>
  <div class="alert-actions"><a id="xAviso" title="Limpar mensagens de erro"><i class="icon-remove">x</i></a></div>
</div></div></perdcomp-painel-mensagens>
<perdcomp-barra-botoes><button name="btnProsseguir" type="button">Prosseguir</button></perdcomp-barra-botoes>
<script>
const m = document.body.dataset;
m.etapa = 'ident'; m.envios = '0'; m.cliquesDcomp = '0';
const $ = (s) => document.querySelector(s);
const mostrar = (id) => document.getElementById(id).classList.remove('oculto');
const esconder = (id) => document.getElementById(id).classList.add('oculto');
const msg = (t) => { $('#msgs').textContent = t; $('#alerta').classList.toggle('oculto', !t); };
document.addEventListener('click', (ev) => {
  if (ev.target.closest('#xAviso')) { msg(''); m.avisoFechado = '1'; }
});
const etapa = (t) => { $('#etapa').textContent = t; };
const carregar = () => { mostrar('carregando'); setTimeout(() => esconder('carregando'), 1000); };
const mascara = (el, cortes) => el.addEventListener('input', () => {
  const d = el.value.replace(/\\D/g, ''); let s = '';
  for (const [a, b, sep] of cortes) { if (d.length > a) s += sep + d.slice(a, b); }
  el.value = s;
});
mascara($('#perdcompAnterior'), [[0,5,''],[5,10,'.'],[10,16,'.'],[16,17,'.'],[17,18,'.'],[18,20,'.'],[20,24,'-']]);
mascara($('#tela-responsavel input'), [[0,3,''],[3,6,'.'],[6,9,'.'],[9,11,'-']]);
$('.icon-NovoDocumento').addEventListener('click', () => mostrar('novo'));
document.querySelectorAll('#novo input[name=tipoDocumento]').forEach(i => i.addEventListener('click', () => {
  m.cliquesDcomp = String(Number(m.cliquesDcomp) + 1);
  if (i.parentElement.querySelector('i').dataset.value === '3') setTimeout(() => mostrar('perguntas'), 100);
}));
document.querySelectorAll('#perguntas input').forEach(i => i.addEventListener('click', () => {
  if (i.parentElement.textContent.trim() === 'Não') setTimeout(() => mostrar('campos'), 100);
}));
$('#tipoIdentificacaoCredito').addEventListener('change', (e) => {
  if (e.target.value === '2: Object') mostrar('perdcompAnterior');
});
document.querySelectorAll('#modal-termo input').forEach(i => i.addEventListener('click', () => {
  m.termo = i.parentElement.textContent.trim();
}));
$('#botaoOkTermoAceito').addEventListener('click', () => {
  if (m.termo !== 'Não') return;
  esconder('modal-termo');
  if (txt('tipoCredito') === 'Pagamento Indevido ou a Maior') { mostrar('tela-ci'); m.etapa = 'ci1'; }
  else { mostrar('tela-litigio'); m.etapa = 'litigio'; }
});
const aba = (n) => document.querySelectorAll('#tela-ci li.tab').forEach((li, i) => li.classList.toggle('active', i === n));
$('[name=btnIncluir]').addEventListener('click', () => mostrar('form-debito'));
let apagouVencimento = false;
$('#dataVencimento').addEventListener('blur', () => {
  if (__APAGA_VENCIMENTO__ && !apagouVencimento && $('#dataVencimento').value) {
    apagouVencimento = true;
    setTimeout(() => { $('#dataVencimento').value = ''; m.vencimentoApagado = '1'; }, 300);
  }
});
$('#grupoTributo').addEventListener('change', () => mostrar('receita-wrap'));
const txt = (id) => { const s = document.getElementById(id); return s.options[s.selectedIndex].textContent.trim(); };
document.querySelectorAll('button').forEach(b => { if (b.textContent.trim() === 'Confirmar') b.addEventListener('click', () => {
  m.grupo = txt('grupoTributo'); m.tipoDebito = txt('tipoDebito'); m.receita = txt('tributoExtensaoReceita');
  m.periodo = $('#periodoApuracao').value; m.vencimento = $('#dataVencimento').value; m.valor = $('#valorPrincipal').value;
  if (m.receita === 'Selecione...' || !m.valor) { msg('Preencha o débito.'); return; }
  esconder('form-debito'); m.debitoConfirmado = '1';
}); });
const desfecho = () => setTimeout(() => {
  if ('__DESFECHO__' === 'pago') msg('A TRANSMISSÃO NÃO FOI CONCLUÍDA. O PER/DCOMP NÃO FOI TRANSMITIDO. PEDIDO DE RESTITUIÇÃO OU RESSARCIMENTO DO MESMO CRÉDITO TEVE O PAGAMENTO REALIZADO OU ESTÁ EM FASE DE PAGAMENTO.');
  if ('__DESFECHO__' === 'outro') msg('__MSG_OUTRO__');
  if ('__DESFECHO__' === 'recusado') msg('Não é possível prosseguir neste momento. Tente novamente mais tarde. [1795027582597]');
  if ('__DESFECHO__' === 'enviado') mostrar('popup-enviado');
  // texto real da tela (linha 131 da incorporadora, 23/11/2026)
  if ('__DESFECHO__' === 'duplicado') msg('Este documento possui as mesmas características do PER/DCOMP 28581.16014.231126.1.3.04-5722, transmitido em 23/11/2026 às 14:11:13. Não é permitida a transmissão de documentos em duplicidade');
}, 400);
$('[name=btnEnviar]').addEventListener('click', () => {
  m.envios = String(Number(m.envios) + 1);
  $('[name=btnEnviar]').disabled = true;
  if (__PENDENCIAS__) setTimeout(() => mostrar('popup-pendencias'), 300); else desfecho();
});
$('#botaoNaoVerificarPendenciasNaoImpeditivas').addEventListener('click', () => {
  m.pendencias = String(Number(m.pendencias || 0) + 1); esconder('popup-pendencias'); desfecho();
});
$('#botaoNavegarTelaInicial').addEventListener('click', () => { esconder('popup-enviado'); m.ok = '1'; });
$('[name=btnProsseguir]').addEventListener('click', () => {
  msg(''); carregar();
  if (m.etapa === 'ident') {
    if ($('#perdcompAnterior').value.replace(/\\D/g, '').length !== 24) { msg('Campo obrigatório.'); return; }
    if (__CANCELADO__) {
      m.recusasCancelado = String(Number(m.recusasCancelado || 0) + 1);
      // HTML real enviado pelo usuário (19/11/2026)
      $('#msgs').innerHTML = '<p _ngcontent-ng-c148673025=""><span _ngcontent-ng-c148673025="" class="ng-star-inserted"><span _ngcontent-ng-c148673025="">O documento que contém o detalhamento do crédito encontra-se cancelado</span><br _ngcontent-ng-c148673025=""></span><!----></p>';
      $('#alerta').classList.remove('oculto');
      return;
    }
    if ('__TIPO_CORRETO__' && txt('tipoCredito').indexOf('__TIPO_CORRETO__') !== 0) {
      m.recusasTipo = String(Number(m.recusasTipo || 0) + 1);
      msg('Tipo do crédito informado neste documento diferente do tipo de crédito do PER/DCOMP que contém o detalhamento do crédito');
      return;
    }
    esconder('novo'); m.etapa = 'termo';
    if (__COM_TERMO__) mostrar('modal-termo'); else { mostrar('tela-litigio'); m.etapa = 'litigio'; }
  } else if (m.etapa === 'ci1') {
    setTimeout(() => { aba(1); esconder('ci-ident'); m.etapa = 'ci2'; }, 300);
  } else if (m.etapa === 'ci2') {
    setTimeout(() => { aba(2); mostrar('tela-credito'); m.etapa = 'credito'; m.passouCi = '1'; }, 300);
  } else if (m.etapa === 'litigio') {
    const c = $('[formcontrolname=litigioProcJudicial]');
    if (!c.checked) { msg('Marque a declaração.'); return; }
    m.litigio = '1'; esconder('tela-litigio'); mostrar('tela-credito'); m.etapa = 'credito';
  } else if (m.etapa === 'credito') {
    m.credito = $('#creditoOriginalDataEntrega').value;
    if (!m.credito) { msg('Informe o crédito.'); return; }
    esconder('tela-credito'); esconder('tela-ci'); mostrar('tela-debitos'); m.etapa = 'debitos';
  } else if (m.etapa === 'debitos') {
    if (m.debitoConfirmado !== '1') { msg('Informe um débito.'); return; }
    esconder('tela-debitos'); mostrar('tela-responsavel'); m.etapa = 'responsavel';
  } else if (m.etapa === 'responsavel') {
    m.cpf = $('#tela-responsavel input').value;
    esconder('tela-responsavel');
    if (__VOLTA_CREDITO__) { mostrar('tela-credito'); etapa('Informar Crédito'); m.etapa = 'credito'; return; }
    mostrar('tela-pendencias'); m.etapa = 'pendencias'; etapa('Verificar Pendências');
    if (__VAZIA__) { msg('Não é possível prosseguir neste momento. Tente novamente mais tarde.'); }
    else if (__APTO__) setTimeout(() => mostrar('apto'), 300);
    else { $('#tela-pendencias').insertAdjacentHTML('beforeend', '<div class="erro">O Documento não está apto para envio (1)</div>' + '<perdcomp-verificar-pendencias><div name="pendencia"><div class="col-xs-1"><i class="icon-remove_sign error"></i></div><div class="col-xs-5"><a>Contribuinte</a></div><div class="col-xs-6"><a>Empresa baixada pelo motivo INCORPORACAO: o acesso ao PERDCOMP Web deverá ser feito pela empresa sucessora</a></div></div><div name="pendencia"><div class="col-xs-1"><i class="icon-warning_sign alerta"></i></div><div class="col-xs-6"><a>Aviso que não impede</a></div></div></perdcomp-verificar-pendencias>'); }
  } else if (m.etapa === 'pendencias') {
    esconder('tela-pendencias'); mostrar('tela-envio'); m.etapa = 'envio';
  }
});
</script></body></html>"""


MSG_OUTRO = ("A TRANSMISSÃO NÃO FOI CONCLUÍDA. O PER/DCOMP NÃO FOI TRANSMITIDO. "
             "O CRÉDITO INFORMADO ESTÁ VINCULADO A PROCESSO EM ANÁLISE.")


def _app(*, desfecho="pago", apto=True, pendencias_vazias=False, com_termo=True, pendencias=False, volta_credito=False,
         apaga_vencimento=False, tipo_correto="", cancelado=False) -> str:
    substituicoes = {
        "__RADIOS__": _radios(OPCOES_REAIS),
        "__RETIFICADORA__": _retificadora(),
        "__TIPO_CREDITO__": _select("tipoCredito", "tipoCredito", TIPOS_CREDITO),
        "__QUALIFICACAO__": _select("qualificacaoContribuinte", "qualificacaoContribuinte",
                                    ["Outra Qualificação", "Sociedade Cooperativa Agropecuária ou de Consumo"]),
        "__DETALHAMENTO__": _select("tipoIdentificacaoCredito", "tipoIdentificacaoCredito",
                                    ["O crédito será detalhado neste documento",
                                     "O crédito já foi detalhado em PER/DCOMP anterior",
                                     "O crédito já foi detalhado em Processo Administrativo"]),
        "__GRUPO__": _select("grupoTributo", "grupoTributo", ["CIDE", "COFINS", "CSLL", "PIS/PASEP"]),
        "__TIPO_DEBITO__": _select("tipoDebito", "tipoDebito",
                                   ["Débito do próprio contribuinte", "Débito de empresa sucedida"]),
        "__RECEITA__": _select("tributoExtensaoReceita", "tributoExtensaoReceita", RECEITAS),
        "__NUMERO__": NUMERO_ENVIADO,
        "__DESFECHO__": desfecho,
        "__APTO__": "true" if apto else "false",
        "__VAZIA__": "true" if pendencias_vazias else "false",
        "__COM_TERMO__": "true" if com_termo else "false",
        "__PENDENCIAS__": "true" if pendencias else "false",
        "__VOLTA_CREDITO__": "true" if volta_credito else "false",
        "__TIPO_CORRETO__": tipo_correto,
        "__CANCELADO__": "true" if cancelado else "false",
        "__APAGA_VENCIMENTO__": "true" if apaga_vencimento else "false",
        "__MSG_OUTRO__": MSG_OUTRO,
    }
    texto = _HTML
    for chave, valor in substituicoes.items():
        texto = texto.replace(chave, valor)
    return texto


@pytest.fixture
def abrir(navegador):
    paginas = []

    def _abrir(**kwargs):
        page = navegador.new_page(viewport={"width": 1200, "height": 900})
        paginas.append(page)
        srcdoc = html.escape(_app(**kwargs), quote=True)
        page.set_content(f'<html><body style="margin:0"><iframe id="frmApp" '
                         f'style="width:1180px;height:880px;border:0" srcdoc="{srcdoc}"></iframe>'
                         "</body></html>")
        page.frame_locator("#frmApp").locator("#novo").wait_for(state="attached")
        return page

    yield _abrir
    for page in paginas:
        page.close()


def _estado(page) -> dict:
    frame = next(f for f in page.frames if f != page.main_frame)
    return frame.evaluate("() => ({...document.body.dataset})")


def _declaracao(page, **kwargs):
    fp.preencher_identificacao(page, tributo="COFINS", perdcomp=PERDCOMP, timeout=5_000)
    return et.concluir_declaracao(
        page, conferencias_identificacao=fp.conferencias_identificacao(
            page, tributo="COFINS", perdcomp=PERDCOMP), **kwargs)


def test_pagamento_indevido_passa_pelas_abas_do_credito_sem_litigio(abrir):
    """Passos do usuário (20/11/2026): termo -> Prosseguir (Identificação do
    Crédito) -> Prosseguir (Detalhamento) -> 10,00 -> Prosseguir -> débito."""
    page = abrir(desfecho="enviado")
    fp.preencher_identificacao(page, tributo="PAGAMENTO INDEVIDO", perdcomp=PERDCOMP, timeout=5_000)
    desfecho = et.concluir_declaracao(
        page, permitir_envio=True, pagamento_indevido=True,
        conferencias_identificacao=fp.conferencias_identificacao(
            page, tributo="PAGAMENTO INDEVIDO", perdcomp=PERDCOMP))
    estado = _estado(page)
    assert desfecho.situacao == SITUACAO_PROTOCOLADA
    assert estado["passouCi"] == "1" and "litigio" not in estado
    assert estado["credito"] == "10,00" and estado["grupo"] == "COFINS"
    assert estado["envios"] == "1"


def test_pagamento_realizado(abrir):
    page = abrir(desfecho="pago")
    momentos = []
    desfecho = _declaracao(page, permitir_envio=True,
                           antes_de_enviar=lambda: momentos.append(_estado(page)["envios"]))
    estado = _estado(page)
    assert desfecho.situacao == SITUACAO_PAGAMENTO_REALIZADO and desfecho.ok
    assert momentos == ["0"]               # o diário anota ANTES do clique
    assert estado["envios"] == "1"         # um clique só no "Enviar"
    # os valores fixos pedidos pelo usuário
    assert estado["termo"] == "Não" and estado["litigio"] == "1"
    assert estado["credito"] == "10,00"
    assert (estado["grupo"], estado["tipoDebito"], estado["receita"]) == (
        "COFINS", "Débito do próprio contribuinte", "5856-01 - Cofins - Não cumulativa")
    assert (estado["periodo"], estado["vencimento"], estado["valor"]) == ("10/2026", "25/11/2026", "0,01")
    assert estado["cpf"] == "059.038.299-37"
    assert estado["cliquesDcomp"] == "1"


def test_declaracao_enviada_le_o_numero_e_clica_ok(abrir):
    page = abrir(desfecho="enviado")
    desfecho = _declaracao(page, permitir_envio=True)
    assert desfecho.situacao == SITUACAO_PROTOCOLADA
    assert NUMERO_ENVIADO in desfecho.detalhe
    assert _estado(page).get("ok") == "1"
    assert desfecho.tela_conhecida


def test_duplicidade_e_protocolada_com_o_numero_ja_transmitido(abrir):
    """Linha 131 da incorporadora (23/11/2026): a 1ª tentativa ouviu "Não é
    possível prosseguir", mas a Receita transmitiu; a 2ª recebeu o aviso de
    duplicidade. É a Declaração que já existe: protocolada, com o número dela."""
    from VerificacaoPagamento.desfechos import numero_documento

    page = abrir(desfecho="duplicado")
    desfecho = _declaracao(page, permitir_envio=True)
    assert desfecho.situacao == SITUACAO_PROTOCOLADA and desfecho.ok
    assert numero_documento(desfecho.detalhe) == "28581.16014.231126.1.3.04-5722"
    assert _estado(page)["envios"] == "1"
    assert _estado(page).get("ok") is None   # não há popup de "OK" a clicar
    assert not desfecho.tela_conhecida        # a próxima linha recarrega o módulo


def test_nao_apto_nao_envia(abrir, monkeypatch):
    monkeypatch.setattr(et, "ESPERA_APTO_MS", 1_500)
    page = abrir(apto=False)
    retratos = []
    desfecho = _declaracao(page, permitir_envio=True, diagnostico=retratos.append)
    # o porquê vai para a AA (usuário, 21/11/2026), só as pendências impeditivas
    assert desfecho.situacao == (f"{SITUACAO_NAO_APTO} — Empresa baixada pelo motivo INCORPORACAO: "
                                 "o acesso ao PERDCOMP Web deverá ser feito pela empresa sucessora")
    assert _estado(page)["envios"] == "0"
    assert "nao_apto" in retratos


def test_pendencias_vazias_com_nao_e_possivel_prosseguir_e_erro_e_nao_nao_apto(abrir, monkeypatch):
    """Linhas 4824/4825 (19/11/2026): a Verificação de Pendências veio vazia,
    com "Não é possível prosseguir", e foi gravada como "não apto"."""
    from VerificacaoPagamento.formulario_perdcomp import ProsseguirNaoAvancou

    monkeypatch.setattr(et, "ESPERA_APTO_MS", 1_500)
    page = abrir(pendencias_vazias=True)
    retratos = []
    with pytest.raises(ProsseguirNaoAvancou, match="nem 'nao apto'"):
        _declaracao(page, permitir_envio=True, diagnostico=retratos.append)
    assert _estado(page)["envios"] == "0"
    assert "nao_apto" not in retratos


def test_modo_seguro_para_no_apto_sem_clicar_enviar(abrir):
    page = abrir(desfecho="enviado")
    desfecho = _declaracao(page, permitir_envio=False)
    assert desfecho.situacao == "" and desfecho.ok
    assert "MODO SEGURO" in desfecho.detalhe
    assert _estado(page)["envios"] == "0"


def test_sem_desfecho_depois_do_enviar_e_quarentena(abrir, monkeypatch):
    monkeypatch.setattr(et, "ESPERA_RESULTADO_ENVIO_MS", 2_000)
    page = abrir(desfecho="nenhum")
    with pytest.raises(EnvioSemConfirmacao):
        _declaracao(page, permitir_envio=True)
    assert _estado(page)["envios"] == "1"  # e não houve segundo clique


def test_sem_o_popup_do_termo_segue_direto_para_o_litigio(abrir):
    page = abrir(com_termo=False, desfecho="pago")
    desfecho = _declaracao(page, permitir_envio=True)
    assert desfecho.situacao == SITUACAO_PAGAMENTO_REALIZADO
    assert "termo" not in _estado(page)


def test_outro_motivo_grava_a_mensagem_da_receita(abrir):
    page = abrir(desfecho="outro")
    desfecho = _declaracao(page, permitir_envio=True)
    assert desfecho.situacao == MSG_OUTRO
    assert desfecho.ok and desfecho.tela_conhecida
    assert _estado(page)["envios"] == "1"


def test_pendencias_nao_impeditivas_responde_nao_e_segue(abrir):
    page = abrir(desfecho="pago", pendencias=True)
    desfecho = _declaracao(page, permitir_envio=True)
    estado = _estado(page)
    assert desfecho.situacao == SITUACAO_PAGAMENTO_REALIZADO
    assert (estado["envios"], estado["pendencias"]) == ("1", "1")


def test_pendencias_e_declaracao_enviada(abrir):
    page = abrir(desfecho="enviado", pendencias=True)
    desfecho = _declaracao(page, permitir_envio=True)
    assert desfecho.situacao == SITUACAO_PROTOCOLADA
    assert _estado(page)["pendencias"] == "1"


def test_tela_que_volta_para_informar_credito_e_erro_e_nao_nao_apto(abrir, monkeypatch):
    """Execução real de 18/11/2026, linha 71: depois do CPF a tela voltou para
    'Informar Crédito' e isso tinha sido gravado como 'não apto'."""
    from VerificacaoPagamento.formulario_perdcomp import ProsseguirNaoAvancou

    monkeypatch.setattr(et, "ESPERA_APTO_MS", 1_500)
    page = abrir(volta_credito=True)
    retratos = []
    with pytest.raises(ProsseguirNaoAvancou, match="Informar Cr"):
        _declaracao(page, permitir_envio=True, diagnostico=retratos.append)
    assert _estado(page)["envios"] == "0"
    assert "etapa_inesperada" in retratos


def test_campo_que_a_pagina_apagou_e_refeito_antes_de_confirmar(abrir):
    """A página 'perdeu' a data de vencimento depois de preenchida: a conferência
    antes do 'Confirmar' percebe e preenche de novo."""
    page = abrir(apaga_vencimento=True, desfecho="pago")
    desfecho = _declaracao(page, permitir_envio=True)
    estado = _estado(page)
    assert estado.get("vencimentoApagado") == "1"
    assert estado["vencimento"] == "25/11/2026"
    assert desfecho.situacao == SITUACAO_PAGAMENTO_REALIZADO


def test_espera_a_pagina_parar_de_carregar_antes_de_conferir(abrir, monkeypatch):
    chamadas = []
    original = fp.pagina_carregando
    monkeypatch.setattr(fp, "pagina_carregando", lambda page: chamadas.append(original(page)) or chamadas[-1])
    page = abrir(desfecho="pago")
    _declaracao(page, permitir_envio=True)
    assert "perdcomp-loading *" in chamadas  # viu o carregamento e esperou


def test_tipo_de_credito_divergente_e_detectado_na_hora(abrir):
    """A Receita diz que o PIS/COFINS está trocado: a etapa para logo (sem
    esperar o prazo do Prosseguir) com TipoCreditoDivergente; refeita com o
    outro tributo, a declaração segue."""
    import time

    from VerificacaoPagamento.desfechos import TipoCreditoDivergente

    page = abrir(tipo_correto="PIS", desfecho="pago")
    inicio = time.monotonic()
    with pytest.raises(TipoCreditoDivergente):
        _declaracao(page, permitir_envio=True)               # COFINS: recusado
    assert time.monotonic() - inicio < fp.ESPERA_AVANCO_MS / 1000
    assert _estado(page)["envios"] == "0"
    fp.preencher_identificacao(page, tributo="PIS", perdcomp=PERDCOMP, timeout=5_000)
    desfecho = et.concluir_declaracao(
        page, permitir_envio=True,
        conferencias_identificacao=fp.conferencias_identificacao(page, tributo="PIS", perdcomp=PERDCOMP))
    assert desfecho.situacao == SITUACAO_PAGAMENTO_REALIZADO
    assert _estado(page)["recusasTipo"] == "1"


def test_perdcomp_cancelado_e_detectado_na_hora(abrir):
    """Mensagem real (19/11/2026) no Prosseguir da identificação: para logo com
    PerdcompCancelado, sem esperar o prazo e sem enviar nada."""
    import time

    from VerificacaoPagamento.desfechos import PerdcompCancelado

    page = abrir(cancelado=True, desfecho="pago")
    inicio = time.monotonic()
    with pytest.raises(PerdcompCancelado):
        _declaracao(page, permitir_envio=True)
    assert time.monotonic() - inicio < fp.ESPERA_AVANCO_MS / 1000
    estado = _estado(page)
    assert estado["envios"] == "0"
    assert estado["recusasCancelado"] == "1"


def test_envio_recusado_pelo_servidor_nao_e_quarentena(abrir, monkeypatch):
    """Linhas 73 e 509 (18/11/2026): depois do Enviar, o aviso "Não é possível
    prosseguir" e o botão Enviar de volta (ainda marcado como desabilitado).
    Não transmitiu: EnvioRecusadoPeloServidor (a linha é refeita), e não
    EnvioSemConfirmacao (quarentena)."""
    from VerificacaoPagamento.desfechos import EnvioRecusadoPeloServidor

    monkeypatch.setattr(et, "RECUSA_CONFIRMADA_S", 1)
    page = abrir(desfecho="recusado")
    with pytest.raises(EnvioRecusadoPeloServidor):
        _declaracao(page, permitir_envio=True)
    assert _estado(page)["envios"] == "1"


@pytest.mark.parametrize("tipo", ["pago", "outro"])
def test_aviso_da_transmissao_fecha_no_x_so_quando_chamado(abrir, tipo):
    page = abrir(desfecho=tipo)
    desfecho = _declaracao(page, permitir_envio=True)
    assert desfecho.depois_de_gravar is not None
    # o aviso continua na tela até o resultado ser gravado
    assert "TRANSMISSÃO NÃO FOI CONCLUÍDA" in fp.mensagens_da_tela(page)
    assert _estado(page).get("avisoFechado") is None
    desfecho.depois_de_gravar()
    assert _estado(page).get("avisoFechado") == "1"
    assert "TRANSMISSÃO NÃO FOI CONCLUÍDA" not in fp.mensagens_da_tela(page)


def test_declaracao_enviada_nao_tem_aviso_para_fechar(abrir):
    page = abrir(desfecho="enviado")
    desfecho = _declaracao(page, permitir_envio=True)
    assert desfecho.depois_de_gravar is None
