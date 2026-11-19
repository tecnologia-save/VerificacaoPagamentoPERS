"""Leitura do perfil ativo no shell do e-CAC. Dados FICTÍCIOS."""
from VerificacaoPagamento.sessao import cnpj_do_texto_de_perfil


def test_procurador_de_vale_mais_que_o_titular():
    texto = ("Titular (Acesso GOV.BR por Certificado): 24.245.826/0001-89 - PROCURADORA FICTICIA\n"
             "Procurador de: 09.435.440/0001-46 - EMPRESA FICTICIA LTDA")
    assert cnpj_do_texto_de_perfil(texto) == "09435440000146"


def test_sem_procuracao_e_o_titular():
    texto = "Titular (Acesso GOV.BR por Certificado): 24.245.826/0001-89 - EMPRESA FICTICIA"
    assert cnpj_do_texto_de_perfil(texto) == "24245826000189"


def test_sem_cnpj_legivel():
    assert cnpj_do_texto_de_perfil("") == ""
    assert cnpj_do_texto_de_perfil("Procurador de: (carregando)") == ""


def test_espera_o_portal_voltar_sem_abrir_navegador():
    from VerificacaoPagamento.sessao import esperar_portal

    respostas = iter([False, False, True])
    chamadas = []
    esperar_portal(espera_s=0, sonda=lambda: chamadas.append(1) or next(respostas))
    assert len(chamadas) == 3


def test_portal_fora_alem_do_teto_vira_login_nao_concluido():
    import pytest

    from VerificacaoPagamento.sessao import LoginNaoConcluido, esperar_portal

    with pytest.raises(LoginNaoConcluido, match="fora do ar"):
        esperar_portal(espera_s=0, maximo_s=0, sonda=lambda: False)
