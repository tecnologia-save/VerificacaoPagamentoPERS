"""Da identificação preenchida até o desfecho da Declaração de Compensação.

Passos enviados pelo usuário em 18/11/2026:

  1. "Prosseguir" -> popup do termo (inconstitucionalidade): "Não" + "OK";
  2. checkbox "O Contribuinte não está litigando..." -> "Prosseguir";
  3. "Crédito Original na Data de Entrega" = 10,00 -> "Prosseguir";
  4. "Informar Débito": COFINS / Débito do próprio contribuinte / 5856-01 /
     período 10/2026 / vencimento 25/11/2026 / valor 1 -> "Confirmar";
  5. "Prosseguir" -> CPF do responsável -> "Prosseguir";
  6. "O Documento está apto para envio"? Não: AA = "Documento não apto...";
  7. Sim: "Prosseguir" -> "Enviar" e o desfecho:
       - "A TRANSMISSÃO NÃO FOI CONCLUÍDA ... TEVE O PAGAMENTO REALIZADO ..."
           -> AA = "Pagamento realizado";
       - "A TRANSMISSÃO NÃO FOI CONCLUÍDA" por OUTRO motivo
           -> AA = a mensagem da Receita, inteira;
       - popup "Declaração foi enviada com sucesso" (+ número)
           -> AA = "Pagamento não realizado, protocolação feita"; "OK".
     O popup opcional de "pendências não impeditivas" que pode vir depois do
     "Enviar" é respondido com "Não" (não revisar), e a transmissão segue.

O "Enviar" TRANSMITE uma Declaração de Compensação de verdade. Por isso:
  - sem `permitir_envio` (trava de config) a linha para no "apto" sem clicar;
  - `antes_de_enviar()` é chamado ANTES do clique (o diário registra a
    tentativa: se o robô cair ali, a linha nunca é reenviada);
  - um clique SÓ: o fallback (evento direto) só entra se o clique deu erro,
    nenhum desfecho apareceu e o botão continua habilitado;
  - qualquer coisa fora dos desfechos conhecidos depois do clique vira
    EnvioSemConfirmacao (quarentena "Verificar no e-CAC").
"""
from __future__ import annotations

import re
import time

from .config import (
    CPF_RESPONSAVEL,
    CREDITO_ORIGINAL_DATA_ENTREGA,
    DEBITO_DATA_VENCIMENTO,
    DEBITO_GRUPO_TRIBUTO,
    DEBITO_PERIODO_APURACAO,
    DEBITO_RECEITA,
    DEBITO_TIPO,
    DEBITO_VALOR_PRINCIPAL,
    SITUACAO_NAO_APTO,
    SITUACAO_PAGAMENTO_REALIZADO,
    SITUACAO_PROTOCOLADA,
)
from .desfechos import (
    Desfecho,
    EnvioRecusadoPeloServidor,
    EnvioSemConfirmacao,
    PerdcompCancelado,
    PerdcompNaoPertence,
    TipoCreditoDivergente,
)
from .formulario_perdcomp import (
    ESPERA_AVANCO_MS,
    CampoNaoEncontrado,
    ProsseguirNaoAvancou,
    _frame,
    _marcada,
    _primeiro_visivel,
    _texto_normalizado,
    aguardar_pagina_pronta,
    avancar,
    clicar_botao,
    clicar_radio_confirmado,
    conf_checkbox,
    conf_digitos,
    conf_radio,
    conf_select,
    conf_valor,
    conferir_antes_de_avancar,
    esperar_algum,
    etapa_ativa,
    marcar_checkbox_confirmado,
    mensagens_da_tela,
    navegador_fechou,
    preencher_digitando,
    preencher_valor_confirmado,
    prosseguir_ate,
    selecionar,
)

# ── Seletores (HTML real enviado pelo usuário) ───────────────────────────────
SELETOR_TERMO = "input[name='termoAceito']"
SELETOR_OK_TERMO = "#botaoOkTermoAceito"
SELETOR_LITIGIO = "input[formcontrolname='litigioProcJudicial']"
SELETOR_CREDITO_ORIGINAL = "#creditoOriginalDataEntrega"
# Pagamento Indevido ou a Maior (passos do usuário, 20/11/2026): depois do termo
# vem "Informar Crédito" com abas — Identificação do Crédito (campos travados,
# "Detentor do Crédito" = #detentor) -> Prosseguir -> Detalhamento do Crédito ->
# Prosseguir -> Demonstrativo (#creditoOriginalDataEntrega = 10,00) -> Prosseguir
# -> "Informar Débito" como no PIS/COFINS. Não há o checkbox de não litígio.
SELETOR_DETENTOR = "#detentor"
SELETOR_ABA_DETALHAMENTO = "li.tab.active:has-text('Detalhamento do Crédito')"
SELETOR_INFORMAR_DEBITO = "button[name='btnIncluir']"
SELETOR_GRUPO_TRIBUTO = "#grupoTributo"
SELETOR_TIPO_DEBITO = "#tipoDebito"
SELETOR_RECEITA = "#tributoExtensaoReceita"
SELETOR_PERIODO = "#periodoApuracao"
SELETOR_VENCIMENTO = "#dataVencimento"
SELETOR_VALOR_PRINCIPAL = "#valorPrincipal"
# <button type="button">Confirmar</button> — sem id nem name.
SELETOR_CONFIRMAR = "button:text-is('Confirmar')"
SELETOR_CPF = "input[placeholder='999.999.999-99']"
SELETOR_ENVIAR = "button[name='btnEnviar']"
SELETOR_NAO_PENDENCIAS_NAO_IMPEDITIVAS = "#botaoNaoVerificarPendenciasNaoImpeditivas"
SELETOR_OK_TELA_INICIAL = "#botaoNavegarTelaInicial"

TEXTO_APTO = "O Documento está apto para envio"
# "O Documento não está apto para envio (1)" + a lista das pendências (tela real, ARABICA).
TEXTO_NAO_APTO = "não está apto para envio"
# Trechos das mensagens do desfecho. O "pagamento realizado" vem DENTRO do
# "A TRANSMISSÃO NÃO FOI CONCLUÍDA", por isso é conferido primeiro.
TEXTO_PAGAMENTO_REALIZADO = "TEVE O PAGAMENTO REALIZADO"
TEXTO_TRANSMISSAO_NAO_CONCLUIDA = "TRANSMISSÃO NÃO FOI CONCLUÍDA"
TEXTO_ENVIADA = "Declaração foi enviada com sucesso"
from .desfechos import RX_NUMERO_DOCUMENTO  # noqa: E402 — a regex vive em desfechos

ESPERA_APTO_MS = 20_000
# Recusa do servidor só conta depois de estável por este tempo (o popup de
# sucesso nunca vem depois disso com o Enviar habilitado de novo).
RECUSA_CONFIRMADA_S = 10
TEXTO_NAO_PROSSEGUIR = "não é possível prosseguir"
# Aviso da Receita quando o PIS/COFINS da linha não é o do PER/DCOMP anterior
# (HTML enviado pelo usuário, 18/11/2026).
TEXTO_TIPO_CREDITO_DIVERGENTE = "tipo de crédito do per/dcomp que contém o detalhamento"
# "O documento que contém o detalhamento do crédito encontra-se cancelado"
# (HTML enviado pelo usuário, 19/11/2026).
TEXTO_PERDCOMP_CANCELADO = "detalhamento do crédito encontra-se cancelado"
# "O PER/DCOMP informado não pertence ao contribuinte e nem a uma empresa
# sucedida" (HTML enviado pelo usuário, 21/11/2026): troca o tipo de crédito.
TEXTO_PERDCOMP_NAO_PERTENCE = "não pertence ao contribuinte"


# "Aguarde a página carregar": a transmissão pode demorar (nas Protocolações já
# levou mais de 1 min com a Receita lenta).
ESPERA_RESULTADO_ENVIO_MS = 180_000


def _texto_visivel(page, trecho: str) -> bool:
    """Algum elemento VISÍVEL contém `trecho` (sem diferenciar maiúsculas)."""
    return _primeiro_visivel(_frame(page).get_by_text(trecho, exact=False)) is not None


def _formatar_cpf(digitos: str) -> str:
    return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"


# ── Etapas ───────────────────────────────────────────────────────────────────
#
# Cada avanço (Prosseguir, OK do termo, Confirmar do débito) passa antes por
# `conferir_antes_de_avancar`: página parada + TODOS os dados da tela relidos
# e aceitos pelo formulário (regra do usuário depois da linha 71, 18/11/2026).

def _localizar_nao_termo(page):
    return _primeiro_visivel(
        _frame(page).locator(f"label:has({SELETOR_TERMO})").filter(has_text=re.compile(r"^\s*Não\s*$")))


def _responder_termo_nao(page, diagnostico=None) -> None:
    rotulo = None
    limite = time.monotonic() + 10
    while rotulo is None and time.monotonic() < limite:
        rotulo = _localizar_nao_termo(page)
        if rotulo is None:
            time.sleep(0.25)
    if rotulo is None:
        raise CampoNaoEncontrado("A opcao 'Nao' do termo de inconstitucionalidade nao apareceu.")
    clicar_radio_confirmado(
        rotulo, seletor_input=SELETOR_TERMO,
        reagiu=lambda: _marcada(rotulo, SELETOR_TERMO),
        nome="Termo de inconstitucionalidade = Nao", proximo="a marcacao",
        diagnostico=diagnostico, rotulo_diagnostico="termo",
    )


# Aviso que às vezes aparece no "Prosseguir" da identificação: o PER/DCOMP
# informado não é o original — "gostaria de recuperar o original?". Regra do
# usuário (19/11/2026): clicar "Sim" e seguir normalmente. Sem o HTML exato,
# o aviso é reconhecido pelo conteúdo: um botão visível "Sim" dentro de um
# bloco curto de texto que fala em "original".
_JS_SIM_DO_ORIGINAL = r"""(body) => {
  const visivel = (el) => {
    const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  document.querySelectorAll('[data-auto-sim-original]').forEach(e => e.removeAttribute('data-auto-sim-original'));
  const botoes = [...document.querySelectorAll('button, a, input[type=button], input[type=submit]')]
    .filter(b => visivel(b) && ((b.innerText || b.value || '').trim().toLowerCase() === 'sim'));
  const textoDosBotoes = (c) => [...c.querySelectorAll('button, a, input')]
    .map(b => (b.innerText || b.value || '')).join(' ');
  for (const b of botoes) {
    // O aviso é o MENOR bloco em volta do botão que tem texto além dos botões;
    // a decisão é só sobre ele (não sobe até a página, que pode ter "Crédito
    // Original" em outro lugar).
    let c = b.parentElement;
    for (let i = 0; c && i < 8; i++, c = c.parentElement) {
      const t = (c.innerText || '').replace(/\s+/g, ' ').trim();
      const semBotoes = t.replace(textoDosBotoes(c).replace(/\s+/g, ' ').trim(), '').trim();
      if (semBotoes.length < 15) continue;
      if (t.length <= 700 && /original/i.test(t)) {
        b.setAttribute('data-auto-sim-original', '1');
        return t.slice(0, 300);
      }
      break;
    }
  }
  return '';
}"""


def responder_recuperar_original(page) -> bool:
    """Se o aviso "não é o original ... recuperar o original?" estiver na
    tela (no app ou na página), clica "Sim". True se clicou."""
    for alvo in (_frame(page), page):
        try:
            texto = alvo.locator("body").first.evaluate(_JS_SIM_DO_ORIGINAL, timeout=2_000)
        except Exception as e:
            if navegador_fechou(e):
                raise
            continue
        if not texto:
            continue
        botao = alvo.locator("[data-auto-sim-original='1']").first
        print(f"  -> Aviso de PER/DCOMP nao original ({texto[:120]!r}): clicando 'Sim'.")
        try:
            botao.click(timeout=10_000)
        except Exception as e:
            if navegador_fechou(e):
                raise
            botao.evaluate("(el) => el.click()")
        return True
    return False


def termo_e_litigio(page, diagnostico=None, conferencias_identificacao=(), *,
                    pagamento_indevido: bool = False) -> None:
    """Passos 1-2: "Prosseguir" da identificação, termo "Não" + OK, checkbox
    (no Pagamento Indevido não há checkbox: o termo leva a "Informar Crédito")."""
    proxima = (SELETOR_DETENTOR,) if pagamento_indevido else (SELETOR_LITIGIO,)
    respostas_original = [0]

    def _tipo_divergente() -> bool:
        return TEXTO_TIPO_CREDITO_DIVERGENTE in mensagens_da_tela(page).casefold()

    def _cancelado() -> bool:
        return TEXTO_PERDCOMP_CANCELADO in mensagens_da_tela(page).casefold()

    def _nao_pertence() -> bool:
        return TEXTO_PERDCOMP_NAO_PERTENCE in mensagens_da_tela(page).casefold()

    def _vigiar() -> bool:
        # Enquanto espera a próxima tela: responde "Sim" ao aviso do PER/DCOMP
        # não original (no máximo 3 vezes) e para se o tipo de crédito divergir
        # ou se o PER/DCOMP estiver cancelado.
        if respostas_original[0] < 3 and responder_recuperar_original(page):
            respostas_original[0] += 1
        return _cancelado() or _tipo_divergente() or _nao_pertence()

    apareceu = prosseguir_ate(page, (SELETOR_TERMO, *proxima), "identificacao",
                              conferencias=conferencias_identificacao, diagnostico=diagnostico,
                              parar_se=_vigiar)
    if not apareceu and _cancelado():
        raise PerdcompCancelado(mensagens_da_tela(page)[:200])
    if not apareceu and _tipo_divergente():
        raise TipoCreditoDivergente(mensagens_da_tela(page)[:200])
    if not apareceu and _nao_pertence():
        raise PerdcompNaoPertence(mensagens_da_tela(page)[:200])
    if apareceu == SELETOR_TERMO:
        print("FASE: Termo de inconstitucionalidade -> Nao + OK")
        frame = _frame(page)
        _responder_termo_nao(page, diagnostico)
        avancar(page, lambda: clicar_botao(frame, SELETOR_OK_TERMO, descricao="'OK' do termo"),
                proxima, "'OK' do termo",
                conferencias=[conf_radio(page, lambda: _localizar_nao_termo(page), SELETOR_TERMO,
                                         "Termo = Nao", lambda: _responder_termo_nao(page))],
                diagnostico=diagnostico, rotulo_diagnostico="termo_nao_fechou")
    if pagamento_indevido:
        return
    print("FASE: Declaracao de nao litigio")
    marcar_checkbox_confirmado(page, SELETOR_LITIGIO, "Nao litigio judicial/administrativo")


def credito_original(page, diagnostico=None, *, pagamento_indevido: bool = False) -> None:
    """Passo 3."""
    if pagamento_indevido:
        print("FASE: Informar Credito -> Identificacao do Credito")
        apareceu = prosseguir_ate(page, (SELETOR_ABA_DETALHAMENTO, SELETOR_CREDITO_ORIGINAL),
                                  "identificacao do credito", diagnostico=diagnostico)
        if apareceu == SELETOR_ABA_DETALHAMENTO:
            print("FASE: Informar Credito -> Detalhamento do Credito")
            prosseguir_ate(page, (SELETOR_CREDITO_ORIGINAL,), "detalhamento do credito",
                           diagnostico=diagnostico)
    else:
        prosseguir_ate(page, (SELETOR_CREDITO_ORIGINAL,), "nao litigio",
                       conferencias=[conf_checkbox(page, SELETOR_LITIGIO, "Nao litigio")],
                       diagnostico=diagnostico)
    print("FASE: Credito Original na Data de Entrega")
    preencher_valor_confirmado(page, SELETOR_CREDITO_ORIGINAL, CREDITO_ORIGINAL_DATA_ENTREGA,
                               "Credito Original na Data de Entrega")
    prosseguir_ate(page, (SELETOR_INFORMAR_DEBITO,), "credito original",
                   conferencias=[conf_valor(page, SELETOR_CREDITO_ORIGINAL, CREDITO_ORIGINAL_DATA_ENTREGA,
                                            "Credito Original na Data de Entrega")],
                   diagnostico=diagnostico)


def _conferencias_debito(page) -> list:
    return [
        conf_select(page, SELETOR_GRUPO_TRIBUTO, DEBITO_GRUPO_TRIBUTO, "Grupo de Tributo"),
        conf_select(page, SELETOR_TIPO_DEBITO, DEBITO_TIPO, "Tipo de Debito"),
        conf_select(page, SELETOR_RECEITA, DEBITO_RECEITA, "Codigo da Receita"),
        conf_digitos(page, SELETOR_PERIODO, DEBITO_PERIODO_APURACAO, "Periodo de Apuracao"),
        conf_digitos(page, SELETOR_VENCIMENTO, DEBITO_DATA_VENCIMENTO, "Data de Vencimento"),
        conf_valor(page, SELETOR_VALOR_PRINCIPAL, DEBITO_VALOR_PRINCIPAL, "Valor Principal"),
    ]


def informar_debito(page, diagnostico=None) -> None:
    """Passo 4: o débito simbólico (valores fixos de config)."""
    print("FASE: Informar Debito")
    frame = _frame(page)
    avancar(page, lambda: clicar_botao(frame, SELETOR_INFORMAR_DEBITO, descricao="'Informar Debito'"),
            (SELETOR_GRUPO_TRIBUTO,), "'Informar Debito'", diagnostico=diagnostico,
            rotulo_diagnostico="informar_debito")
    selecionar(page, SELETOR_GRUPO_TRIBUTO, DEBITO_GRUPO_TRIBUTO, "Grupo de Tributo")
    selecionar(page, SELETOR_TIPO_DEBITO, DEBITO_TIPO, "Tipo de Debito")
    selecionar(page, SELETOR_RECEITA, DEBITO_RECEITA, "Codigo da Receita")
    preencher_digitando(page, SELETOR_PERIODO, DEBITO_PERIODO_APURACAO, "Periodo de Apuracao")
    preencher_digitando(page, SELETOR_VENCIMENTO, DEBITO_DATA_VENCIMENTO, "Data de Vencimento")
    preencher_valor_confirmado(page, SELETOR_VALOR_PRINCIPAL, DEBITO_VALOR_PRINCIPAL, "Valor Principal")

    conferir_antes_de_avancar(page, _conferencias_debito(page), "'Confirmar' do debito", diagnostico)
    clicar_botao(frame, SELETOR_CONFIRMAR, descricao="'Confirmar'")
    print("  -> 'Confirmar' clicado.")
    # O débito entrou quando o formulário dele sai da tela.
    limite = time.monotonic() + ESPERA_AVANCO_MS / 1000
    while _primeiro_visivel(frame.locator(SELETOR_GRUPO_TRIBUTO)) is not None:
        if time.monotonic() >= limite:
            mensagens = mensagens_da_tela(page)
            if diagnostico is not None:
                diagnostico("debito_nao_confirmado")
            raise ProsseguirNaoAvancou(
                "Depois de 'Confirmar' o formulario do debito continuou na tela"
                + (f": {mensagens}" if mensagens else ".")
            )
        time.sleep(0.3)
    print("  -> Debito informado.")


def _conferencia_cpf(page):
    return conf_digitos(page, SELETOR_CPF, CPF_RESPONSAVEL, "CPF do responsavel",
                        formatado=_formatar_cpf(CPF_RESPONSAVEL))


def responsavel(page, diagnostico=None) -> None:
    """Passo 5 (até o CPF preenchido)."""
    prosseguir_ate(page, (SELETOR_CPF,), "debito", diagnostico=diagnostico)
    print("FASE: CPF do responsavel")
    preencher_digitando(page, SELETOR_CPF, CPF_RESPONSAVEL, "CPF do responsavel",
                        formatado=_formatar_cpf(CPF_RESPONSAVEL))


ETAPA_PENDENCIAS = "verificar pendencias"


def _normalizar_etapa(texto: str) -> str:
    import unicodedata

    texto = unicodedata.normalize("NFD", (texto or "").casefold())
    return " ".join("".join(c for c in texto if unicodedata.category(c) != "Mn").split())


def documento_apto(page, diagnostico=None) -> bool:
    """Passo 6: "Prosseguir" e a mensagem "O Documento está apto para envio".

    "Não apto" só quando a tela está COMPROVADAMENTE na etapa "Verificar
    Pendências" (`ul.circular-steps p.active`), parada, e a mensagem não veio.
    Execução real de 18/11/2026, linha 71: depois do CPF a tela voltou para
    "Informar Crédito" e isso foi lido como "não apto" — agora é erro da linha
    (nada vai para a AA; ela é refeita)."""
    prosseguir_ate(page, (f"text={TEXTO_APTO}", "ul.circular-steps p.active"), "responsavel",
                   conferencias=[_conferencia_cpf(page)], diagnostico=diagnostico)
    limite = time.monotonic() + ESPERA_APTO_MS / 1000
    etapa = ""
    while time.monotonic() < limite:
        if _texto_visivel(page, TEXTO_APTO):
            print("  -> Documento apto para envio: True")
            return True
        if _texto_visivel(page, TEXTO_NAO_APTO):
            break
        time.sleep(0.3)
    aguardar_pagina_pronta(page)
    if _texto_visivel(page, TEXTO_APTO):
        print("  -> Documento apto para envio: True")
        return True
    etapa = etapa_ativa(page)
    if _normalizar_etapa(etapa) != ETAPA_PENDENCIAS:
        mensagens = mensagens_da_tela(page)
        if diagnostico is not None:
            diagnostico("etapa_inesperada")
        raise ProsseguirNaoAvancou(
            f"Depois de 'Prosseguir' (responsavel) a tela foi para '{etapa or '?'}', e nao para "
            "'Verificar Pendencias'" + (f": {mensagens}" if mensagens else ".")
        )
    if not _texto_visivel(page, TEXTO_NAO_APTO):
        # Verificação de Pendências VAZIA, ou com "Não é possível prosseguir"
        # (linhas 4824/4825, 19/11/2026: gravadas como "não apto" no meio de uma
        # queda do e-CAC). Sem a mensagem de não apto, é erro: a linha é refeita.
        mensagens = mensagens_da_tela(page)
        if diagnostico is not None:
            diagnostico("pendencias_sem_resultado")
        raise ProsseguirNaoAvancou(
            "Verificar Pendencias sem 'apto' nem 'nao apto' na tela"
            + (f": {mensagens}" if mensagens else "."))
    print("  -> Documento apto para envio: False (a tela diz que nao esta apto)")
    if diagnostico is not None:
        diagnostico("nao_apto")
    return False


def _envio_recusado(page) -> bool:
    """O aviso "Não é possível prosseguir neste momento" está no painel E o
    botão "Enviar" está visível e habilitado de novo (a tela voltou ao ponto de
    antes do clique — o servidor não aceitou a transmissão)."""
    # O aviso é procurado na TELA (e não só no primeiro painel de mensagens: há
    # mais de um no DOM), e o botão "Enviar" basta estar presente — na linha
    # 509 (18/11/2026) ele voltou à tela marcado como "processando", e a
    # exigência de "habilitado" deixou a recusa passar como envio sem resposta.
    if not _texto_visivel(page, TEXTO_NAO_PROSSEGUIR):
        return False
    return _primeiro_visivel(_frame(page).locator(SELETOR_ENVIAR)) is not None


SELETOR_AVISO_TRANSMISSAO = "perdcomp-painel-mensagens .alert2"
SELETOR_X_DO_AVISO = ".alert-actions a"  # title="Limpar mensagens de erro", ícone icon-remove


def fechar_aviso_transmissao(page) -> bool:
    """Fecha no "X" o aviso "A TRANSMISSÃO NÃO FOI CONCLUÍDA" (pagamento
    realizado ou outro motivo) e confere que sumiu. Chamado DEPOIS que o
    resultado foi gravado. Nunca levanta por causa da tela: o resultado já
    está gravado; True se o aviso sumiu."""
    frame = _frame(page)
    aviso = _primeiro_visivel(frame.locator(SELETOR_AVISO_TRANSMISSAO).filter(
        has_text=TEXTO_TRANSMISSAO_NAO_CONCLUIDA))
    if aviso is None:
        return not _texto_visivel(page, TEXTO_TRANSMISSAO_NAO_CONCLUIDA)
    x = _primeiro_visivel(aviso.locator(SELETOR_X_DO_AVISO))
    if x is None:
        print("  -> [AVISO] O 'X' do aviso de transmissao nao foi encontrado.")
        return False
    for tentativa in range(2):
        try:
            if tentativa == 0:
                x.click(timeout=5_000)
            else:
                x.evaluate("(el) => el.click()")
        except Exception as e:
            if navegador_fechou(e):
                raise
        limite = time.monotonic() + 3
        while time.monotonic() < limite:
            if not _texto_visivel(page, TEXTO_TRANSMISSAO_NAO_CONCLUIDA):
                print("  -> Aviso da transmissao fechado no 'X'.")
                return True
            time.sleep(0.2)
    print("  -> [AVISO] O aviso de transmissao continuou na tela depois do 'X'.")
    return False


def _desfecho_do_envio(page) -> Desfecho | None:
    """Um dos desfechos conhecidos já está na tela? None = ainda não."""
    if _texto_visivel(page, TEXTO_PAGAMENTO_REALIZADO):
        return Desfecho(True, "A Receita recusou a transmissão: o crédito já teve o pagamento "
                              "realizado (ou está em fase de pagamento).",
                        situacao=SITUACAO_PAGAMENTO_REALIZADO,
                        depois_de_gravar=lambda: fechar_aviso_transmissao(page))
    enviada = _primeiro_visivel(_frame(page).get_by_text(TEXTO_ENVIADA, exact=False))
    if enviada is not None:
        achado = RX_NUMERO_DOCUMENTO.search(_texto_normalizado(enviada))
        numero = achado.group(0) if achado else ""
        print(f"  -> Declaracao enviada. Numero do documento: {numero or '(nao lido)'}")
        return Desfecho(True, f"Declaração enviada — nº {numero or 'não lido'}",
                        situacao=SITUACAO_PROTOCOLADA)
    nao_concluida = _primeiro_visivel(
        _frame(page).get_by_text(TEXTO_TRANSMISSAO_NAO_CONCLUIDA, exact=False))
    if nao_concluida is not None:
        # Não transmitiu, por OUTRO motivo: a AA recebe a mensagem da Receita
        # inteira, do mesmo elemento onde viria a do pagamento realizado
        # (regra do usuário, 18/11/2026).
        mensagem = _texto_normalizado(nao_concluida)[:1000] or TEXTO_TRANSMISSAO_NAO_CONCLUIDA
        if TEXTO_PAGAMENTO_REALIZADO.casefold() in mensagem.casefold():
            # A mensagem do pagamento realizado vem DENTRO desta; se ela surgiu
            # entre as duas conferências (linha 837, 19/11/2026), vale a regra
            # do pagamento realizado.
            return Desfecho(True, "A Receita recusou a transmissão: o crédito já teve o pagamento "
                                  "realizado (ou está em fase de pagamento).",
                            situacao=SITUACAO_PAGAMENTO_REALIZADO,
                            depois_de_gravar=lambda: fechar_aviso_transmissao(page))
        print(f"  -> Transmissao nao concluida (outro motivo): {mensagem}")
        return Desfecho(True, f"Transmissão não concluída: {mensagem}", situacao=mensagem,
                        depois_de_gravar=lambda: fechar_aviso_transmissao(page))
    return None


def _responder_pendencias_nao_impeditivas(page) -> bool:
    """Popup OPCIONAL "O documento examinado apresenta pendências que não
    impedem seu envio à RFB": responde "Não" (não revisar), e a transmissão
    segue — confirmado pelo usuário em 18/11/2026 para esta automação. Mesmo
    botão das Protocolações. True se respondeu."""
    botao = _primeiro_visivel(_frame(page).locator(SELETOR_NAO_PENDENCIAS_NAO_IMPEDITIVAS))
    if botao is None:
        return False
    print("  -> Pendencias nao impeditivas: 'Nao' (segue com a transmissao).")
    try:
        botao.click(timeout=10_000)
    except Exception as e:
        if navegador_fechou(e):
            raise
        botao.evaluate("(el) => el.click()")  # clique pelo DOM, sem depender de rolagem
    return True


def enviar(page, *, antes_de_enviar=None, diagnostico=None) -> Desfecho:
    """Passo 7. Levanta EnvioSemConfirmacao se, depois do clique em "Enviar",
    nenhum desfecho conhecido aparecer (ou o navegador cair)."""
    frame = _frame(page)
    prosseguir_ate(page, (SELETOR_ENVIAR,), "verificacao de pendencias", diagnostico=diagnostico)
    botao = _primeiro_visivel(frame.locator(SELETOR_ENVIAR))
    if botao is None:
        raise CampoNaoEncontrado("O botao 'Enviar' nao esta na tela.")

    if antes_de_enviar is not None:
        antes_de_enviar()  # diário: tentativa registrada ANTES do clique

    print("FASE: Enviar")
    try:
        try:
            botao.click(timeout=20_000)
            print("  -> 'Enviar' clicado.")
        except Exception as e:
            # O clique pode ter saído mesmo com erro: só dispara de novo se
            # nenhum desfecho apareceu E o botão continua habilitado.
            if navegador_fechou(e):
                raise
            print(f"  -> [AVISO] Clique em 'Enviar' falhou ({type(e).__name__}); conferindo a tela...")
            time.sleep(3)
            if (_desfecho_do_envio(page) is None and botao.is_visible() and botao.is_enabled()):
                botao.dispatch_event("click")
                print("  -> 'Enviar' disparado direto no elemento.")

        limite = time.monotonic() + ESPERA_RESULTADO_ENVIO_MS / 1000
        respostas_pendencias = 0
        proxima_resposta = 0.0
        recusado_desde: float | None = None
        while time.monotonic() < limite:
            desfecho = _desfecho_do_envio(page)
            if desfecho is not None:
                break
            # Recusa do servidor: aviso "Não é possível prosseguir" + o Enviar
            # habilitado de novo, sem desfecho, por RECUSA_CONFIRMADA_S seguidos.
            if _envio_recusado(page):
                recusado_desde = recusado_desde or time.monotonic()
                if time.monotonic() - recusado_desde >= RECUSA_CONFIRMADA_S:
                    if diagnostico is not None:
                        diagnostico("envio_recusado_pelo_servidor")
                    raise EnvioRecusadoPeloServidor(
                        f"o e-CAC recusou o envio: {mensagens_da_tela(page)[:200]}")
            else:
                recusado_desde = None
            # No máximo 2 respostas, com 5 s entre elas: a 2ª só se o popup
            # continuar na tela (o primeiro clique não pegou).
            if respostas_pendencias < 2 and time.monotonic() >= proxima_resposta:
                if _responder_pendencias_nao_impeditivas(page):
                    respostas_pendencias += 1
                    proxima_resposta = time.monotonic() + 5
            time.sleep(0.5)
        else:
            if diagnostico is not None:
                diagnostico("envio_sem_confirmacao")
            raise EnvioSemConfirmacao(
                f"'Enviar' clicado e nenhum desfecho apareceu em {ESPERA_RESULTADO_ENVIO_MS // 1000}s"
                + (f" (tela: {mensagens_da_tela(page)})" if mensagens_da_tela(page) else "")
            )
    except (EnvioSemConfirmacao, EnvioRecusadoPeloServidor):
        raise
    except Exception as e:
        # Depois do Enviar, qualquer falha vira quarentena: não se sabe se transmitiu.
        raise EnvioSemConfirmacao(f"falha depois do 'Enviar': {type(e).__name__}: {e}"[:300],
                                  navegador_morto=navegador_fechou(e)) from e
    print(f"  -> Desfecho do envio: {desfecho.situacao or desfecho.detalhe}")

    if desfecho.situacao == SITUACAO_PROTOCOLADA:
        # "OK" do popup (volta à tela inicial). O envio já está confirmado: se
        # o OK falhar, a linha continua certa — só a próxima recarrega o módulo.
        try:
            clicar_botao(frame, SELETOR_OK_TELA_INICIAL, descricao="'OK' do envio")
            esperar_algum(page, ("i.icon-NovoDocumento",), 10_000)
        except Exception as e:  # noqa: BLE001 — o envio está confirmado; não perde o desfecho
            # Mesmo com o navegador caído aqui, o desfecho vale: a linha é
            # gravada como protocolada e a próxima reabre a sessão.
            print(f"  -> [AVISO] 'OK' do envio nao clicado ({type(e).__name__}).")
            desfecho.tela_conhecida = False
    return desfecho


def concluir_declaracao(page, *, permitir_envio: bool, antes_de_enviar=None,
                        diagnostico=None, conferencias_identificacao=(),
                        pagamento_indevido: bool = False) -> Desfecho:
    """Passos 1-7, com a identificação já preenchida. `conferencias_identificacao`:
    o que a identificação informou, relido antes do primeiro "Prosseguir".
    `pagamento_indevido`: tipo de crédito "Pagamento Indevido ou a Maior"."""
    termo_e_litigio(page, diagnostico, conferencias_identificacao,
                    pagamento_indevido=pagamento_indevido)
    credito_original(page, diagnostico, pagamento_indevido=pagamento_indevido)
    informar_debito(page, diagnostico)
    responsavel(page, diagnostico)
    if not documento_apto(page, diagnostico):
        return Desfecho(True, "Documento não apto para envio", situacao=SITUACAO_NAO_APTO)
    if not permitir_envio:
        return Desfecho(True, "Apto para envio — MODO SEGURO: 'Enviar' não foi clicado")
    return enviar(page, antes_de_enviar=antes_de_enviar, diagnostico=diagnostico)
