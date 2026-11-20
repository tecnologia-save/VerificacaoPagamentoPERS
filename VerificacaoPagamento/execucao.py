"""Orquestração do lote: certificado > empresa > linha.

Não conhece Tkinter nem patchright: tudo que toca o navegador passa pelo
`portal` (ver `portal.PortalReal`; nos testes, um dublê). Assim as regras do
lote são testáveis sem abrir o Chrome:

  - UM navegador por certificado: todas as empresas dele, trocando só o
    perfil; no fim do certificado, Sair com Segurança e fecha;
  - o perfil ativo é CONFERIDO ao entrar em cada empresa (a troca do
    `ecac_login` pode "dar certo" sem ter trocado — ver sessao.py);
  - empresa com "mensagens importantes": processada normalmente, mas no fim
    dela Caixa Postal -> Sair -> fecha, e a próxima empresa faz login novo
    (com o popup não dá para trocar o perfil);
  - empresa recusada pelo e-CAC (procuração expirada, etc.) não derruba as
    outras do mesmo certificado;
  - login que falha 2x seguidas com o mesmo certificado encerra aquele
    certificado e segue para o próximo;
  - navegador que cai: a linha falha e a próxima reabre a sessão;
  - parada do operador (BaseException) atravessa tudo, mas a sessão aberta
    ainda sai com segurança (finally).
"""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import time as hora_do_dia
from pathlib import Path

from .certificados import (
    Certificado,
    CertificadoIndisponivel,
    carregar_certificado,
    resolver_nome,
)
from .config import (
    CODIGOS_CREDITO_ATENDIDOS,
    SITUACAO_MENSAGENS_IMPORTANTES,
    SITUACAO_SEM_PERMISSAO,
    MAX_ENVIOS_SEM_CONFIRMACAO,
    PROCURADORES_IGNORADOS,
    SITUACAO_VERIFICAR,
    STATUS_Z_A_PROCESSAR,
)
from .desfechos import (
    EmpresaBloqueadaNaCaixaPostal,
    SemPermissaoPerdcomp,
    EnvioRecusadoPeloServidor,
    EnvioSemConfirmacao,
    ExecucaoInterrompida,
    TipoCreditoDivergente,
)
from .formulario_perdcomp import navegador_fechou
from .planilha import (
    DadosPlanilha,
    GrupoCertificado,
    codigo_credito,
    LinhaPerdcomp,
    normalizar_texto,
    planejar_lote,
    status_z_permitido,
)
from .sessao import LoginNaoConcluido, PerfilRecusado

# Logins seguidos que falham com o mesmo certificado antes de desistir dele.
MAX_FALHAS_LOGIN_POR_CERTIFICADO = 2
# Vezes que uma linha é feita (1ª + refeitas) quando cai ANTES do Enviar.
# Navegador que caiu / sessão que não abriu: reabre NA HORA, insistindo, em vez
# de deixar as linhas da empresa para o próximo passe (pedido do usuário,
# 18/11/2026: os navegadores devem ficar abertos o tempo todo).
MAX_REABERTURAS = 3
# Queda de conexão com a Receita (net::ERR_..., ex. ERR_SOCKS_CONNECTION_FAILED
# do proxy do certificado — 18/11/2026, quedas de ~5 min a cada ~30 min): não
# gasta as tentativas da linha — espera o portal voltar e refaz. Teto de
# esperas para não ficar preso numa linha (cada uma >= ESPERA_ERRO_REDE_S).
MAX_ESPERAS_REDE_LINHA = 60

# O Receitanet (transmissão) fica fora do ar todo dia das 1h às 3h (aviso do
# e-CAC, 19/11/2026: linha 839 sem confirmação e "não aptos" falsos). Regra do
# usuário: nesse horário a automação para e volta às 3h01. Nenhuma linha
# começa a partir de 0h58 — uma linha leva ~40 s e não pode estar no meio à 1h.
JANELA_RECEITANET = (hora_do_dia(0, 58), hora_do_dia(3, 1))


def _agora() -> datetime:
    return datetime.now()


def _dormir(segundos: float) -> None:
    time.sleep(segundos)


def na_janela_receitanet(agora: datetime) -> bool:
    inicio, fim = JANELA_RECEITANET
    return inicio <= agora.time() < fim
MAX_TENTATIVAS_LINHA = 5


@dataclass
class ResultadoLinha:
    numero_linha: int
    rotulo: str
    ok: bool
    detalhe: str = ""

    def como_resumo(self) -> dict:
        return {"rotulo": self.rotulo, "ok": self.ok, "detalhe": self.detalhe}


@dataclass
class Lote:
    grupos: list[GrupoCertificado]
    certificados: dict[str, Certificado]
    avisos: list[str] = field(default_factory=list)      # vão para o resumo
    informacoes: list[str] = field(default_factory=list)  # só para o log
    linhas_fora: int = 0  # pendentes que não puderam entrar (sem cert., CNPJ inválido...)

    @property
    def total_linhas(self) -> int:
        return sum(g.total_linhas for g in self.grupos)


def erro_de_rede(e: BaseException) -> bool:
    """Falha de conexão do Chrome com o servidor (net::ERR_...), não da tela."""
    return "net::ERR_" in str(e)


def _exemplos(numeros: list[int]) -> str:
    return ", ".join(str(n) for n in numeros[:5]) + ("..." if len(numeros) > 5 else "")


def _cortar(grupos: list[GrupoCertificado], limite_empresas: int | None,
            limite_linhas: int | None) -> list[GrupoCertificado]:
    """As primeiras empresas/linhas NA ORDEM DE PROCESSAMENTO (certificado >
    empresa > linha) — "a primeira empresa" é a primeira que o robô faria."""
    if limite_empresas is None and limite_linhas is None:
        return grupos
    empresas_restantes = limite_empresas if limite_empresas is not None else float("inf")
    linhas_restantes = limite_linhas if limite_linhas is not None else float("inf")
    cortados: list[GrupoCertificado] = []
    for grupo in grupos:
        novo = GrupoCertificado(certificado=grupo.certificado)
        for empresa in grupo.empresas:
            if empresas_restantes <= 0 or linhas_restantes <= 0:
                break
            linhas = empresa.linhas[:int(min(len(empresa.linhas), linhas_restantes))]
            empresa.linhas = linhas
            novo.empresas.append(empresa)
            empresas_restantes -= 1
            linhas_restantes -= len(linhas)
        if novo.empresas:
            cortados.append(novo)
    return cortados


def _prioritarias_primeiro(prioritarios: list[GrupoCertificado],
                           demais: list[GrupoCertificado]) -> list[GrupoCertificado]:
    """Todas as empresas prioritárias antes das outras. O certificado em que as
    prioritárias terminam emenda nas outras empresas dele (sem login a mais)."""
    if prioritarios and demais:
        ultimo = prioritarios[-1].certificado
        for i, grupo in enumerate(demais):
            if grupo.certificado == ultimo:
                prioritarios[-1].empresas.extend(grupo.empresas)
                demais = [grupo for j, grupo in enumerate(demais) if j != i]
                break
    return prioritarios + demais


def preparar_lote(dados: DadosPlanilha, limite: int | None, pfx_disponiveis: dict[str, Path],
                  senhas: dict[str, str], *, limite_empresas: int | None = None,
                  somente_certificado: str | None = None,
                  certificados_incluidos=None, certificados_excluidos=None,
                  status_prioridade=STATUS_Z_A_PROCESSAR,
                  procuradores_ignorados=PROCURADORES_IGNORADOS) -> Lote:
    """Escolhe as linhas, resolve os certificados e agrupa — tudo ANTES do login.

    PRIORIDADE POR EMPRESA (regra do usuário, 18/11/2026): a empresa (CNPJ)
    que tiver PELO MENOS UMA linha com status `status_prioridade` na coluna Z
    é prioritária — INTEIRA, com todas as linhas pendentes dela. Desde
    20/11/2026 as outras empresas também entram, DEPOIS de todas as
    prioritárias. Tupla vazia = sem prioridade (ordem da planilha).

    Depois, por linha: procurador ignorado (ELIANE), CNPJ, tributo (só
    PIS/COFINS por enquanto), nº do PER/DCOMP (24 dígitos), certificado.
    `limite_empresas`/`limite`(linhas) cortam na ordem de processamento.
    Problemas viram AVISOS agregados (com a planilha inteira seriam milhares de
    itens repetindo a mesma causa no resumo); os filtros intencionais
    (prioridade, ignorados) só vão para o log.
    """
    avisos: list[str] = []
    informacoes: list[str] = []
    ignorados = {normalizar_texto(p) for p in procuradores_ignorados}
    # Sobre TODAS as linhas (inclusive as já verificadas): uma empresa cuja
    # linha "Análise concluída" já foi feita continua prioritária no resto.
    prioritarias = ({linha.cnpj for linha in dados.linhas
                     if linha.cnpj and status_z_permitido(linha.status, status_prioridade)}
                    if status_prioridade else None)

    fora_status = 0
    qtd_ignorados = 0
    repetidos = 0
    vistos: set[str] = set()
    cnpj_invalido: list[int] = []
    perdcomp_invalido: list[int] = []
    tributo_fora: Counter[str] = Counter()
    credito_fora: Counter[str] = Counter()
    candidatas: list[LinhaPerdcomp] = []
    for linha in dados.pendentes:
        if normalizar_texto(linha.procurador) in ignorados:
            qtd_ignorados += 1
        elif not linha.cnpj:
            cnpj_invalido.append(linha.numero_linha)
        elif not linha.tipo_tributo:
            tributo_fora[linha.tributo.strip() or "(vazio)"] += 1
        elif len(linha.perdcomp) != 24 or not linha.perdcomp.isdigit():
            perdcomp_invalido.append(linha.numero_linha)
        elif codigo_credito(linha.perdcomp) not in CODIGOS_CREDITO_ATENDIDOS:
            credito_fora[codigo_credito(linha.perdcomp)] += 1
        elif linha.perdcomp in vistos:
            # PER/DCOMP repetido na planilha: só a primeira linha vai ao e-CAC
            # (senão sairiam DUAS Declarações para o mesmo crédito); as outras
            # herdam o resultado dela na reconciliação (registro.reconciliar).
            repetidos += 1
        else:
            vistos.add(linha.perdcomp)
            candidatas.append(linha)
            if prioritarias is not None and linha.cnpj not in prioritarias:
                fora_status += 1

    if prioritarias is not None:
        informacoes.append(f"{len(prioritarias)} empresa(s) com pelo menos uma linha "
                           f"'{' / '.join(status_prioridade)}' (coluna Z) vêm primeiro, inteiras; "
                           f"{fora_status} linha(s) de outras empresas vêm depois delas.")
    if repetidos:
        informacoes.append(f"{repetidos} linha(s) repetem o PER/DCOMP de outra linha: não vão ao "
                           "e-CAC e recebem o resultado da primeira.")
    if qtd_ignorados:
        informacoes.append(f"{qtd_ignorados} linha(s) de procurador ignorado "
                           f"({', '.join(procuradores_ignorados)}) ficaram de fora.")
    if cnpj_invalido:
        avisos.append(f"{len(cnpj_invalido)} linha(s) com CNPJ inválido na coluna D foram "
                      f"puladas (linhas {_exemplos(cnpj_invalido)}).")
    if tributo_fora:
        valores = ", ".join(f"'{v}' ({q})" for v, q in tributo_fora.most_common(6))
        avisos.append(f"{sum(tributo_fora.values())} linha(s) com tributo fora de PIS/COFINS "
                      f"na coluna K foram puladas: {valores}.")
    if credito_fora:
        valores = ", ".join(f"'{c}' ({q})" for c, q in credito_fora.most_common(6))
        avisos.append(f"{sum(credito_fora.values())} linha(s) com PER/DCOMP de outro tipo de "
                      f"crédito (código {valores}; ex.: '04' = restituição de pagamento indevido "
                      "ou a maior) ficaram de fora: o fluxo só preenche ressarcimento de PIS/COFINS "
                      f"({'/'.join(CODIGOS_CREDITO_ATENDIDOS)}). A coluna AA delas fica vazia.")
    if perdcomp_invalido:
        avisos.append(f"{len(perdcomp_invalido)} linha(s) sem um PER/DCOMP de 24 dígitos na "
                      f"coluna M foram puladas (linhas {_exemplos(perdcomp_invalido)}).")

    sem_certificado: Counter[str] = Counter()
    por_arquivo: dict[Path, list[LinhaPerdcomp]] = {}
    for linha in candidatas:
        caminho = resolver_nome(linha.procurador, pfx_disponiveis)
        if caminho is None:
            sem_certificado[linha.procurador.strip() or "(vazio)"] += 1
            continue
        por_arquivo.setdefault(caminho, []).append(linha)
    for procurador, qtd in sem_certificado.most_common():
        avisos.append(
            f"{qtd} linha(s) do procurador '{procurador}' (coluna B) foram puladas: nenhum "
            "certificado .pfx corresponde a esse nome. Se existir, acrescente o apelido em "
            "config.APELIDOS_CERTIFICADO."
        )

    certificados: dict[str, Certificado] = {}
    linhas_ok: list[tuple[LinhaPerdcomp, str]] = []
    recusadas_cert = 0
    for caminho, linhas in por_arquivo.items():
        try:
            certificado = carregar_certificado(caminho, senhas)
        except CertificadoIndisponivel as e:
            avisos.append(f"{len(linhas)} linha(s) do certificado '{caminho.stem}' foram "
                          f"puladas: {e}.")
            recusadas_cert += len(linhas)
            continue
        certificados[certificado.nome] = certificado
        linhas_ok.extend((linha, certificado.nome) for linha in linhas)

    linhas_ok.sort(key=lambda par: par[0].numero_linha)
    if somente_certificado is not None:
        # Navegador aberto: só as empresas do certificado com que ele está logado.
        fora = sum(1 for _, nome in linhas_ok if nome != somente_certificado)
        linhas_ok = [(ln, nome) for ln, nome in linhas_ok if nome == somente_certificado]
        informacoes.append(f"Navegador aberto com o certificado '{somente_certificado}': "
                           f"{fora} linha(s) de outros certificados ficam para depois.")
    # Duas sessões ao mesmo tempo, divididas por certificado (pedido do
    # usuário, 18/11/2026). Vem DEPOIS da remoção de PER/DCOMP repetido, feita
    # na planilha inteira: um mesmo PER/DCOMP nunca vai para as duas sessões.
    if certificados_incluidos or certificados_excluidos:
        incluir = {normalizar_texto(n) for n in certificados_incluidos or ()}
        excluir = {normalizar_texto(n) for n in certificados_excluidos or ()}
        conhecidos = {normalizar_texto(n) for n in certificados}
        for nome in (incluir | excluir) - conhecidos:
            avisos.append(f"Certificado '{nome}' (--certificados/--exceto-certificados) não "
                          "aparece em nenhuma linha do lote.")

        def _desta_sessao(nome: str) -> bool:
            chave = normalizar_texto(nome)
            return (not incluir or chave in incluir) and chave not in excluir

        fora = sum(1 for _, nome in linhas_ok if not _desta_sessao(nome))
        linhas_ok = [(ln, nome) for ln, nome in linhas_ok if _desta_sessao(nome)]
        informacoes.append(f"{fora} linha(s) de certificados de outra sessão ficam fora deste lote.")
    if prioritarias is None:
        grupos = planejar_lote(linhas_ok)
    else:
        grupos = _prioritarias_primeiro(
            planejar_lote([par for par in linhas_ok if par[0].cnpj in prioritarias]),
            planejar_lote([par for par in linhas_ok if par[0].cnpj not in prioritarias]))
    grupos = _cortar(grupos, limite_empresas, limite)
    usados = {g.certificado for g in grupos}
    return Lote(
        grupos=grupos,
        certificados={n: c for n, c in certificados.items() if n in usados},
        avisos=avisos,
        informacoes=informacoes,
        linhas_fora=(len(cnpj_invalido) + sum(tributo_fora.values()) + len(perdcomp_invalido)
                     + sum(sem_certificado.values()) + recusadas_cert),
    )


def executar(lote: Lote, portal, *, checkpoint=None, registro=None,
             resultados: list[ResultadoLinha] | None = None) -> list[ResultadoLinha]:
    """Processa o lote. Devolve um resultado por linha que entrou no lote.

    `registro`: onde os desfechos vão (`registro.RegistroResultados`: diário +
    coluna AA). None = nada é gravado (modo seguro).
    `resultados`, se passado, é preenchido no lugar — quem chamou fica com o
    parcial mesmo quando a parada do operador interrompe no meio.

    Levanta ExecucaoInterrompida depois de MAX_ENVIOS_SEM_CONFIRMACAO envios
    sem confirmação (a sessão ainda sai com segurança)."""
    resultados = [] if resultados is None else resultados
    total = lote.total_linhas
    posicao = 0
    sessao = None
    modulo_aberto = False
    envios_sem_confirmacao = 0

    def _checkpoint():
        if checkpoint is not None:
            checkpoint()

    def _registrar(linha: LinhaPerdcomp, situacao: str, detalhe: str) -> None:
        if registro is not None:
            registro.registrar(linha, situacao, detalhe)

    def _antes_de_enviar(linha: LinhaPerdcomp):
        if registro is None:
            return None
        return lambda: registro.marcar_envio(linha)

    def _falhar(linhas: list[LinhaPerdcomp], detalhe: str) -> None:
        nonlocal posicao
        for linha in linhas:
            posicao += 1
            resultados.append(ResultadoLinha(linha.numero_linha, linha.rotulo, False, detalhe))

    def _largar_sessao(*, morta: bool = False) -> None:
        nonlocal sessao
        if sessao is not None:
            portal.encerrar(sessao, navegador_morto=morta,
                            via_caixa_postal=bool(getattr(sessao, "mensagens_importantes", False))
                            and not morta)
        sessao = None

    def _entrar_na_empresa(certificado: Certificado, cnpj: str) -> None:
        """Deixa `sessao` no perfil de `cnpj`, CONFERIDO. Levanta PerfilRecusado
        (vale para a empresa) ou LoginNaoConcluido (vale para o certificado)."""
        nonlocal sessao
        login_novo = sessao is None
        if login_novo:
            sessao = portal.abrir_sessao(certificado, cnpj)
        elif sessao.cnpj_ativo != cnpj:
            portal.trocar_empresa(sessao, cnpj)

        lido = portal.cnpj_ativo(sessao)
        if lido != cnpj:
            print(f"  -> [AVISO] Perfil ativo no e-CAC e {lido or '(nao lido)'}, esperado {cnpj}.")
            portal.capturar(sessao, f"perfil_divergente_{cnpj}")
            sessao.mensagens_importantes = portal.tem_mensagens_importantes(sessao)
            _largar_sessao()
            if login_novo:
                raise LoginNaoConcluido("o perfil da empresa não ficou ativo depois do login "
                                        "(mensagens importantes do titular?)")
            # A troca "deu certo" sem trocar — o caso do popup de mensagens
            # importantes da empresa anterior. Login novo, direto neste CNPJ.
            print("  -> Login novo direto no CNPJ da empresa...")
            sessao = portal.abrir_sessao(certificado, cnpj)
            lido = portal.cnpj_ativo(sessao)
            if lido != cnpj:
                portal.capturar(sessao, f"perfil_divergente_{cnpj}")
                _largar_sessao()
                raise LoginNaoConcluido("o perfil da empresa não ficou ativo nem com login novo")
        sessao.cnpj_ativo = cnpj
        sessao.mensagens_importantes = portal.tem_mensagens_importantes(sessao)
        if sessao.mensagens_importantes:
            raise EmpresaBloqueadaNaCaixaPostal("aviso de mensagens importantes não lidas ao entrar "
                                                "na empresa")

    tentou_desbloquear: set[str] = set()

    def _desbloquear(empresa, certificado: Certificado) -> bool:
        """Regra do usuário (19/11/2026, a nova): o aviso de mensagens
        importantes apareceu -> abre na Caixa Postal TODAS as importantes não
        lidas, anota cada uma na aba das mensagens abertas e segue com as linhas
        da empresa. Uma tentativa por empresa nesta execução. False = não deu
        (a regra antiga vale: `_marcar_mensagens_importantes`)."""
        nonlocal modulo_aberto
        abrir = getattr(portal, "abrir_mensagens_importantes", None)
        if abrir is None or sessao is None or empresa.cnpj in tentou_desbloquear:
            return False
        tentou_desbloquear.add(empresa.cnpj)
        nome = empresa.empresa.strip() or empresa.cnpj
        print(f"  -> [CAIXA POSTAL] {nome}: mensagens importantes nao lidas; abrindo na Caixa "
              "Postal...")

        def _anotar(isn: str, assunto: str) -> None:
            if registro is not None and hasattr(registro, "registrar_mensagem"):
                registro.registrar_mensagem(cnpj=empresa.cnpj, empresa=nome,
                                            certificado=certificado.nome, assunto=assunto, isn=isn)

        try:
            abertas = abrir(sessao, empresa.cnpj, ao_abrir=_anotar)
        except Exception as e:  # noqa: BLE001 — sem desbloquear, a regra antiga
            print(f"  -> [CAIXA POSTAL] Nao foi possivel abrir as mensagens: {type(e).__name__}: "
                  f"{str(e)[:160]}")
            if navegador_fechou(e):
                _largar_sessao(morta=True)
            return False
        print(f"  -> [CAIXA POSTAL] {abertas} mensagem(ns) importante(s) aberta(s); seguindo com "
              "as linhas da empresa.")
        sessao.mensagens_importantes = False
        modulo_aberto = False
        return True

    def _marcar_mensagens_importantes(empresa, linha: LinhaPerdcomp, e: Exception) -> str:
        """Quando as mensagens NÃO puderam ser abertas (`_desbloquear` falhou):
        a regra anterior — marca ESTA linha na AA, sai pela Caixa Postal e vai
        para a próxima empresa. A marca não é resultado: a linha volta ao lote
        na próxima execução. Devolve o motivo para as outras linhas da empresa
        (que ficam para o próximo passe)."""
        nonlocal posicao
        print(f"  -> [CAIXA POSTAL] {empresa.empresa.strip() or empresa.cnpj}: {e}. Linha "
              f"{linha.numero_linha} marcada; saindo pela Caixa Postal para a proxima empresa.")
        _registrar(linha, SITUACAO_MENSAGENS_IMPORTANTES, str(e))
        resultados.append(ResultadoLinha(linha.numero_linha, linha.rotulo, True,
                                         f"{SITUACAO_MENSAGENS_IMPORTANTES}: {e}"[:300]))
        if sessao is not None:
            sessao.mensagens_importantes = True
        return f"empresa pulada — {SITUACAO_MENSAGENS_IMPORTANTES} (fica para o próximo passe)"

    def _respeitar_janela_receitanet() -> None:
        """Das 0h58 às 3h01: sai com segurança e espera; depois a sessão é
        reaberta normalmente (pedido do usuário, 19/11/2026)."""
        nonlocal modulo_aberto
        if not na_janela_receitanet(_agora()):
            return
        fim = datetime.combine(_agora().date(), JANELA_RECEITANET[1])
        print(f"\n[RECEITANET] Fora do ar das 1h as 3h: pausa ate {fim:%H:%M} "
              f"(agora {_agora():%H:%M}). Saindo com seguranca...")
        _largar_sessao()
        modulo_aberto = False
        while na_janela_receitanet(_agora()):
            _checkpoint()
            restante = (datetime.combine(_agora().date(), JANELA_RECEITANET[1]) - _agora())
            _dormir(max(1.0, min(60.0, restante.total_seconds())))
        print(f"[RECEITANET] {_agora():%H:%M}: retomando.")

    def _entrar_insistindo(certificado: Certificado, cnpj: str) -> None:
        """`_entrar_na_empresa`, reabrindo o navegador na hora se falhar. Perfil
        recusado não adianta repetir: sobe direto."""
        for rodada in range(1, MAX_REABERTURAS + 1):
            try:
                _entrar_na_empresa(certificado, cnpj)
                return
            except (PerfilRecusado, EmpresaBloqueadaNaCaixaPostal):
                raise
            except Exception as e:  # noqa: BLE001 — reabre e tenta de novo
                _largar_sessao(morta=navegador_fechou(e))
                if rodada == MAX_REABERTURAS:
                    raise
                print(f"  -> [REABRINDO] Sessao nao abriu ({type(e).__name__}: {str(e)[:120]}); "
                      f"abrindo o navegador de novo agora ({rodada + 1}/{MAX_REABERTURAS})...")
                if erro_de_rede(e):
                    aguardar = getattr(portal, "aguardar_rede", None)
                    if aguardar is not None:
                        aguardar()

    for grupo in lote.grupos:
        certificado = lote.certificados[grupo.certificado]
        print("\n" + "=" * 60)
        print(f"CERTIFICADO: {certificado.nome} — {len(grupo.empresas)} empresa(s), "
              f"{grupo.total_linhas} linha(s)")
        print("=" * 60)
        falhas_login = 0
        try:
            for indice_empresa, empresa in enumerate(grupo.empresas):
                if falhas_login >= MAX_FALHAS_LOGIN_POR_CERTIFICADO:
                    restantes = [ln for e in grupo.empresas[indice_empresa:] for ln in e.linhas]
                    print(f"  -> [ERRO] Login com '{certificado.nome}' falhou {falhas_login}x "
                          f"seguidas: pulando as {len(restantes)} linha(s) restantes.")
                    _falhar(restantes, f"login com o certificado '{certificado.nome}' não concluído")
                    break

                _checkpoint()
                _respeitar_janela_receitanet()
                print(f"\n--- Empresa {empresa.empresa.strip() or '?'} — CNPJ {empresa.cnpj} "
                      f"({len(empresa.linhas)} linha(s))")
                try:
                    _entrar_insistindo(certificado, empresa.cnpj)
                    falhas_login = 0
                    modulo_aberto = False
                except PerfilRecusado as e:
                    print(f"  -> [ERRO] e-CAC recusou o perfil da empresa: {e}")
                    _falhar(empresa.linhas, f"e-CAC recusou o perfil da empresa: {e}")
                    continue
                except EmpresaBloqueadaNaCaixaPostal as e:
                    if not _desbloquear(empresa, certificado):
                        posicao += 1
                        motivo = _marcar_mensagens_importantes(empresa, empresa.linhas[0], e)
                        _falhar(empresa.linhas[1:], motivo)
                        _largar_sessao()        # Caixa Postal + Sair com Segurança
                        continue
                    falhas_login = 0
                    modulo_aberto = False
                except LoginNaoConcluido as e:
                    falhas_login += 1
                    print(f"  -> [ERRO] Login nao concluido: {e}")
                    _falhar(empresa.linhas, f"login não concluído: {e}")
                    continue
                except Exception as e:  # noqa: BLE001 — falha só desta empresa
                    print(f"  -> [ERRO] Falha ao entrar na empresa: {type(e).__name__}: {e}")
                    _largar_sessao(morta=navegador_fechou(e))
                    _falhar(empresa.linhas, f"falha na sessão do e-CAC — {type(e).__name__}")
                    continue

                for indice_linha, linha in enumerate(empresa.linhas):
                    _checkpoint()
                    _respeitar_janela_receitanet()
                    if sessao is None:
                        # O navegador caiu numa linha anterior desta empresa.
                        try:
                            _entrar_insistindo(certificado, empresa.cnpj)
                        except EmpresaBloqueadaNaCaixaPostal as e:
                            if not _desbloquear(empresa, certificado):
                                posicao += 1
                                motivo = _marcar_mensagens_importantes(empresa, linha, e)
                                _falhar(empresa.linhas[indice_linha + 1:], motivo)
                                _largar_sessao()
                                break
                        except Exception as e:  # noqa: BLE001 — falha só do resto desta empresa
                            print(f"  -> [ERRO] Nao foi possivel reabrir a sessao: {type(e).__name__}: {e}")
                            _largar_sessao(morta=navegador_fechou(e))
                            _falhar(empresa.linhas[indice_linha:],
                                    f"sessão do e-CAC não reabriu — {type(e).__name__}")
                            break
                        modulo_aberto = False
                    posicao += 1
                    inicio_linha = time.monotonic()
                    print(f"\nLINHA {posicao}/{total} — planilha linha {linha.numero_linha} — "
                          f"PER/DCOMP {linha.perdcomp} [{datetime.now():%H:%M:%S}]")
                    # Instabilidade do e-CAC ("Não é possível prosseguir neste
                    # momento", formulário reiniciado, módulo que não carrega)
                    # derruba a linha ANTES do Enviar: refaz do zero, com o
                    # módulo recarregado, até MAX_TENTATIVAS_LINHA vezes (pedido
                    # do usuário, 18/11/2026). Seguro: nada foi enviado. Depois
                    # do Enviar é EnvioSemConfirmacao — quarentena, nunca refaz.
                    tentativa = 1
                    esperas_rede = 0
                    bloqueada = ""
                    sem_permissao = False
                    while True:
                        try:
                            if not modulo_aberto:
                                print("FASE: Navegacao para o modulo PERDCOMP")
                                portal.abrir_modulo(sessao)
                                modulo_aberto = True
                            desfecho = portal.processar_linha(
                                sessao, linha, antes_de_enviar=_antes_de_enviar(linha))
                            resultados.append(ResultadoLinha(linha.numero_linha, linha.rotulo,
                                                             desfecho.ok, desfecho.detalhe))
                            if desfecho.tributo_corrigido and registro is not None:
                                registro.corrigir_tributo(linha, desfecho.tributo_corrigido)
                            if desfecho.situacao:
                                _registrar(linha, desfecho.situacao, desfecho.detalhe)
                                # Só DEPOIS de gravado: ex. fechar o aviso no "X".
                                if desfecho.depois_de_gravar is not None:
                                    try:
                                        desfecho.depois_de_gravar()
                                    except Exception as e:  # noqa: BLE001 — já gravado
                                        print(f"  -> [AVISO] Acao depois de gravar falhou "
                                              f"({type(e).__name__}); o modulo sera recarregado.")
                                        desfecho.tela_conhecida = False
                            # Tela num estado conhecido: a próxima linha segue direto
                            # pelo "Novo Documento" (pedido do usuário); senão recarrega.
                            modulo_aberto = desfecho.tela_conhecida
                        except SemPermissaoPerdcomp as e:
                            # Regra do usuário (19/11/2026): a procuração não dá poder
                            # para o PER/DCOMP -> AA de todas as linhas da empresa e
                            # próxima empresa.
                            print(f"  -> [SEM PERMISSAO] {empresa.empresa.strip() or empresa.cnpj}: {e}. "
                                  "Linhas da empresa marcadas; proxima empresa.")
                            for outra in empresa.linhas[indice_linha:]:
                                _registrar(outra, SITUACAO_SEM_PERMISSAO, str(e))
                                if outra is not linha:
                                    posicao += 1
                                resultados.append(ResultadoLinha(outra.numero_linha, outra.rotulo,
                                                                 True, SITUACAO_SEM_PERMISSAO))
                            modulo_aberto = False
                            sem_permissao = True
                        except EmpresaBloqueadaNaCaixaPostal as e:
                            # Antes do Enviar (depois dele é EnvioSemConfirmacao):
                            # abre as mensagens e refaz a linha (sem gastar
                            # tentativa); não dando, marca a linha e próxima empresa.
                            modulo_aberto = False
                            if _desbloquear(empresa, certificado):
                                continue
                            bloqueada = _marcar_mensagens_importantes(empresa, linha, e)
                        except EnvioSemConfirmacao as e:
                            envios_sem_confirmacao += 1
                            print(f"  -> [ERRO] Linha {linha.numero_linha}: ENVIO SEM CONFIRMACAO — {e}")
                            _registrar(linha, SITUACAO_VERIFICAR, str(e))
                            resultados.append(ResultadoLinha(
                                linha.numero_linha, linha.rotulo, False,
                                f"{SITUACAO_VERIFICAR}: {e}"[:300]))
                            modulo_aberto = False
                            if e.navegador_morto:
                                _largar_sessao(morta=True)
                            if (MAX_ENVIOS_SEM_CONFIRMACAO is not None
                                    and envios_sem_confirmacao >= MAX_ENVIOS_SEM_CONFIRMACAO):
                                raise ExecucaoInterrompida(
                                    f"{envios_sem_confirmacao} envios ficaram sem confirmação nesta "
                                    "execução — parada por segurança. Confira essas linhas no e-CAC."
                                ) from None
                        except Exception as e:  # noqa: BLE001 — falha só desta linha
                            if isinstance(e, EnvioRecusadoPeloServidor) and registro is not None:
                                # Não transmitiu: anula o "enviando" do diário e refaz.
                                registro.marcar_nao_transmitido(linha, str(e))
                            morto = navegador_fechou(e)
                            print(f"  -> [ERRO] Linha {linha.numero_linha}: {type(e).__name__}: {e}")
                            if not morto:
                                portal.capturar(sessao, f"erro_linha_{linha.numero_linha}")
                            modulo_aberto = False
                            if morto:
                                _largar_sessao(morta=True)
                            if (erro_de_rede(e) and not morto
                                    and esperas_rede < MAX_ESPERAS_REDE_LINHA):
                                esperas_rede += 1
                                print(f"  -> [REDE] Linha {linha.numero_linha}: conexao com a Receita "
                                      f"caiu; esperando o portal voltar ({esperas_rede}/"
                                      f"{MAX_ESPERAS_REDE_LINHA}) — nada foi enviado.")
                                aguardar = getattr(portal, "aguardar_rede", None)
                                if aguardar is not None:
                                    aguardar()
                                continue
                            # A Receita recusou PIS E COFINS: refazer dá o mesmo resultado.
                            if (tentativa < MAX_TENTATIVAS_LINHA
                                    and not isinstance(e, TipoCreditoDivergente)):
                                tentativa += 1
                                print(f"  -> [RETENTATIVA] Linha {linha.numero_linha}: refazendo do zero "
                                      f"(tentativa {tentativa}/{MAX_TENTATIVAS_LINHA}) — nada foi enviado.")
                                try:
                                    if sessao is None:
                                        _entrar_insistindo(certificado, empresa.cnpj)
                                    continue
                                except Exception as e2:  # noqa: BLE001 — sem sessão, a linha falha
                                    _largar_sessao(morta=navegador_fechou(e2))
                                    e = e2
                            resultados.append(ResultadoLinha(linha.numero_linha, linha.rotulo, False,
                                                             f"{type(e).__name__}: {e}"[:300]))
                        break
                    # Tempo da linha (para a estimativa de término), com o desfecho.
                    ultimo = resultados[-1] if resultados else None
                    print(f"TEMPO DA LINHA {linha.numero_linha}: {time.monotonic() - inicio_linha:.0f}s "
                          f"[{datetime.now():%H:%M:%S}] {'OK' if ultimo and ultimo.ok else 'FALHA'} — "
                          f"{(ultimo.detalhe if ultimo else '')[:80]}")
                    if bloqueada:
                        _falhar(empresa.linhas[indice_linha + 1:], bloqueada)
                        break
                    if sem_permissao:
                        break

                # Com mensagens importantes não dá para trocar o perfil: sai
                # pela Caixa Postal e a próxima empresa faz login novo.
                if sessao is not None and getattr(sessao, "mensagens_importantes", False):
                    print("  -> Empresa com mensagens importantes concluida: Caixa Postal, "
                          "Sair com Seguranca e login novo para a proxima.")
                    _largar_sessao()
        finally:
            _largar_sessao()
    return resultados
