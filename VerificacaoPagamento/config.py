"""Constantes da automação de Verificação de Pagamento de PER/DCOMP.

O início do fluxo (login no e-CAC, módulo PER/DCOMP, tela "Novo Documento") é
o mesmo das automações de Protocolação de Restituição e de Ressarcimento — o
PERDCOMP-WEB é um único app Angular por trás das três. Por isso URL, iframe e
seletores de navegação abaixo são os MESMOS já confirmados naquelas automações.
"""
from pathlib import Path

PROJECT_DIR = Path(__file__).parent

# ── e-CAC / PERDCOMP-WEB ─────────────────────────────────────────────────────
# Mesma URL de módulo das Protocolações: um único id atende Restituição,
# Ressarcimento e Declaração de Compensação.
PERDCOMP_URL = "https://cav.receita.fazenda.gov.br/ecac/Aplicacao.aspx?id=10006&origem=menu"

# Iframe que embute o app Angular do PERDCOMP-WEB dentro da página-shell do e-CAC.
FRAME_PERDCOMP = "#frmApp"

# Item "Novo Documento" da barra lateral. Pelo ÍCONE, não pelo texto: o texto
# real é "Novo<br>Documento", e o <br> não insere espaço no textContent
# ("NovoDocumento"), então nenhum get_by_text("Novo Documento") bate.
SELETOR_NAV_NOVO_DOCUMENTO = "i.icon-NovoDocumento"

# Porta de depuração que o `ecac_login` abre no Chrome (--remote-debugging-port).
# Usada só pelo `debug_capturar_tela.py`.
CDP_URL = "http://localhost:9222"

# ── Certificados ─────────────────────────────────────────────────────────────
# Mesmo padrão do VerificaMensagensPagamento (desktop): um .pfx por procurador
# nesta pasta, e as senhas em `senhas.json` ({"<arquivo>.pfx": "<senha>"}).
# A pasta é COMPARTILHADA com outras automações: aqui ela só é lida.
PASTA_CERTIFICADOS = Path(r"C:\Certificados")
ARQUIVO_SENHAS = PASTA_CERTIFICADOS / "senhas.json"

# Coluna B da planilha ("Procurador") -> nome do .pfx (sem extensão).
#
# O casamento é EXATO depois de normalizar (caixa, acentos, espaços e
# pontuação): nunca por semelhança. Certificado errado = entrar no e-CAC como
# outro procurador, e a Declaração de Compensação pode ser enviada de verdade.
# Um nome que não está aqui e não é igual ao nome de um .pfx da pasta fica
# SEM certificado, e as linhas dele vão para o resumo como falha — para alguém
# acrescentar o apelido aqui.
#
# "SAVE" -> Save Inteligência, "GHS" -> GSH e "CRISTIANO VASCONCELOS BOAVENTURA"
# -> Cristiano Vasconcelos: confirmados pelo usuário em 18/11/2026.
APELIDOS_CERTIFICADO = {
    "SAVE": "Save Inteligência",
    "D&S": "D&S",
    "GESTÃO D&S": "D&S",
    "D.S.R.": "DSR",
    "YURI": "YURY",
    "YURY": "YURY",
    "RECUPERA C": "Recupera-C",
    "CRISTIANO": "Cristiano Vasconcelos",
    "CRISTIANO VASCONCELOS BOAVENTURA": "Cristiano Vasconcelos",
    "SERGIO": "Sergio",
    "G S H": "GSH",
    "GHS": "GSH",
}

# Procuradores cujo certificado não é mais usado: as linhas deles ficam fora
# do lote em silêncio (só uma linha no log) — pedido do usuário, 18/11/2026.
# Tipo de crédito, pelo NÚMERO do PER/DCOMP (dígitos 19-20; no número formatado,
# o "19" de 05507.32579.220926.1.1.19-0646): 18/19 = ressarcimento de PIS/COFINS
# não-cumulativo — o único fluxo que a automação preenche. O resto (ex.: "04",
# restituição de pagamento indevido ou a maior, linha 537 de 18/11/2026) é
# recusado pela Receita nos dois tipos: fica fora do lote, com a AA vazia.
CODIGOS_CREDITO_ATENDIDOS = ("18", "19")

PROCURADORES_IGNORADOS = ("ELIANE",)

# ── Planilha ─────────────────────────────────────────────────────────────────
# PRIORIDADE (usuário, 18/11/2026): entra INTEIRA toda empresa (CNPJ) com pelo
# menos uma linha com este status na coluna Z — todas as linhas dela, qualquer
# que seja o status de cada uma. Tupla vazia = todas as empresas.
STATUS_Z_A_PROCESSAR = ("Análise concluída",)

# ── Formulário da Declaração de Compensação ──────────────────────────────────
# Valores FIXOS definidos pelo usuário em 18/11/2026. A Declaração serve só para
# a Receita dizer se o crédito do PER já foi pago: o débito informado é simbólico.
APELIDO_DOCUMENTO = "Verificação Pagamento PER"
CREDITO_ORIGINAL_DATA_ENTREGA = "10,00"
DEBITO_GRUPO_TRIBUTO = "COFINS"                  # sempre, independente do tributo da linha
DEBITO_TIPO = "Débito do próprio contribuinte"
DEBITO_RECEITA = "5856-01 - Cofins - Não cumulativa"
DEBITO_PERIODO_APURACAO = "10/2026"
DEBITO_DATA_VENCIMENTO = "25/11/2026"
# R$ 0,01 — confirmado pelo usuário em 18/11/2026 (o "1" digitado no campo é 1
# centavo). Escrito "0,01", o formato decimal que o campo de moeda
# (perdcompcurrency) recebe nas Protocolações; a conferência lê o valor 0,01.
DEBITO_VALOR_PRINCIPAL = "0,01"
CPF_RESPONSAVEL = "05903829937"

# ── Coluna AA ("Situação da Verificação") ────────────────────────────────────
# Qualquer texto na AA tira a linha das próximas execuções.
SITUACAO_NAO_APTO = "Documento não apto, não possível verificar"
SITUACAO_PAGAMENTO_REALIZADO = "Pagamento realizado"
SITUACAO_PROTOCOLADA = "Pagamento não realizado, protocolação feita"
# A Receita recusou o tipo de crédito com PIS E com COFINS (regra do usuário,
# 18/11/2026): grava isto na AA e segue, no mesmo navegador.
# O aviso de mensagens importantes não lidas apareceu. Regra do usuário
# (19/11/2026, a nova): a automação ABRE as importantes não lidas na Caixa
# Postal (ver caixa_postal.py), anota cada uma na aba ABA_MENSAGENS_ABERTAS e
# segue com a empresa. Esta marca na AA só sobra quando não deu para abrir
# (a regra antiga: marca a linha, Sair com Segurança e próxima empresa) — e
# NÃO é resultado: a linha volta ao lote na próxima execução.
SITUACAO_MENSAGENS_IMPORTANTES = "Mensagens importantes não lidas na Caixa Postal"
# Aba da planilha com uma linha por mensagem importante aberta pela automação.
ABA_MENSAGENS_ABERTAS = "Mensagens importantes abertas"
SITUACAO_TIPO_CREDITO_DIVERGENTE = ("Tipo do crédito informado neste documento diferente do "
                                    "tipo de crédito do PER/DCOMP")
# No "Prosseguir" da identificação: "O documento que contém o detalhamento do
# crédito encontra-se cancelado" (regra do usuário, 19/11/2026): grava isto na
# AA e segue para a próxima linha.
SITUACAO_PERDCOMP_CANCELADO = "Perdcomp cancelado"
# Ao abrir o módulo: "Seu perfil não possui permissão ou a execução exige acesso
# com certificado digital" = a procuração não dá poder para o PER/DCOMP (regra
# do usuário, 19/11/2026): grava isto na AA das linhas da empresa e segue.
SITUACAO_SEM_PERMISSAO = "Procuração sem poder para PER/DCOMP"
# "Enviar" clicado sem desfecho confirmado: NÃO se sabe se a Declaração foi
# transmitida. A linha fica fora de todas as execuções até alguém conferir no
# e-CAC — reenviar poderia gerar uma segunda Declaração de Compensação.
SITUACAO_VERIFICAR = "Verificar no e-CAC (envio sem confirmação)"

# Teto de envios sem confirmação por execução (None = não para). Pedido do
# usuário (18/11/2026): rodar 24 h sem parar. Cada envio sem confirmação
# continua isolado na quarentena e NUNCA é reenviado — parar não protege mais.
MAX_ENVIOS_SEM_CONFIRMACAO = None

# Caixa Postal do e-CAC (mesma URL do VerificaMensagensPagamento). Empresa com
# "mensagens importantes" trava a troca de perfil: no fim dela a automação
# passa por aqui, sai com segurança e faz login de novo.
CAIXA_POSTAL_URL = "https://cav.receita.fazenda.gov.br/ecac/Aplicacao.aspx?id=00006"

# Limite de linhas sugerido no formulário. Campo vazio = todas.
LIMITE_LINHAS_PADRAO = ""

# ==========================================================================
# TRAVA DE SEGURANÇA — controla se a automação pode persistir/enviar algo no
# e-CAC ("Salvar", "Enviar"). A Declaração de Compensação ENVIADA é um
# documento oficial na Receita Federal, sem desfazer.
#
# False -> modo seguro: nenhuma função que salva ou envia pode clicar.
# True  -> execução real.
#
# Não é um checkbox de tela de propósito: destravar exige editar este arquivo,
# para não acontecer por acidente durante testes.
# ==========================================================================
# Destravado em 18/11/2026 a pedido do usuário, para a primeira execução real
# (uma empresa).
PERMITIR_ACOES_REAIS_NO_ECAC = True
