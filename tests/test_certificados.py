"""Procurador -> .pfx: casamento exato, nunca por semelhança. Certificados FICTÍCIOS."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from VerificacaoPagamento.certificados import (
    CertificadoIndisponivel,
    carregar_certificado,
    ler_senhas,
    listar_pfx,
    resolver_nome,
)

NOMES_DA_PASTA = ["Cristiano Vasconcelos", "D&S", "DSR", "GSH", "Morastoni", "Recupera-C",
                  "Save Inteligência", "Save Tecnologia", "Sergio", "YURY"]


@pytest.fixture
def pasta(tmp_path) -> Path:
    for nome in NOMES_DA_PASTA:
        (tmp_path / f"{nome}.pfx").write_bytes(b"x")
    return tmp_path


@pytest.mark.parametrize(("procurador", "esperado"), [
    ("SAVE", "Save Inteligência"),          # confirmado pelo usuário
    ("D&S", "D&S"),
    ("GESTÃO D&S", "D&S"),
    ("DSR", "DSR"),                         # e não D&S
    ("YURI", "YURY"),
    ("YURI ", "YURY"),
    ("Yury", "YURY"),
    ("RECUPERA C", "Recupera-C"),
    ("CRISTIANO", "Cristiano Vasconcelos"),
    ("SERGIO", "Sergio"),
    ("G S H", "GSH"),
    ("GSH", "GSH"),
    ("GHS", "GSH"),                          # confirmado pelo usuário
    ("CRISTIANO VASCONCELOS BOAVENTURA", "Cristiano Vasconcelos"),
    ("D.S.R.", "DSR"),                       # grafia da planilha atualizada
    ("Save Inteligencia", "Save Inteligência"),
    ("Recupera-c", "Recupera-C"),
    ("Cristiano", "Cristiano Vasconcelos"),
    ("MORASTONI", "Morastoni"),
    ("save tecnologia", "Save Tecnologia"),  # nome completo do .pfx também vale
])
def test_resolve(pasta, procurador, esperado):
    assert resolver_nome(procurador, listar_pfx(pasta)).stem == esperado


@pytest.mark.parametrize("procurador", [
    "ELIANE",   # não há .pfx (e o certificado não é mais usado)
    "HSG",      # parecido com GSH, mas ninguém confirmou: não adivinha
    "Save",     # sem apelido explícito, "Save" não escolhe sozinho entre os dois Save
    "",
])
def test_nao_adivinha(pasta, procurador):
    from VerificacaoPagamento.config import APELIDOS_CERTIFICADO

    apelidos = {k: v for k, v in APELIDOS_CERTIFICADO.items() if k != "SAVE"} \
        if procurador == "Save" else APELIDOS_CERTIFICADO
    assert resolver_nome(procurador, listar_pfx(pasta), apelidos) is None


def test_ler_senhas_casa_sem_caixa_e_acento(tmp_path):
    arquivo = tmp_path / "senhas.json"
    arquivo.write_text(json.dumps({"Yury.pfx": "s1", "Save Inteligência.pfx": "s2"}),
                       encoding="utf-8")
    senhas = ler_senhas(arquivo)
    assert senhas["yury"] == "s1"
    assert senhas["save inteligencia"] == "s2"


def test_ler_senhas_ausente(tmp_path):
    with pytest.raises(CertificadoIndisponivel):
        ler_senhas(tmp_path / "nao-existe.json")


def _pfx(caminho: Path, senha: str) -> Path:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
    from cryptography.x509.oid import NameOID

    chave = ec.generate_private_key(ec.SECP256R1())
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "FICTICIO")])
    agora = dt.datetime.now(dt.UTC)
    cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome)
            .public_key(chave.public_key()).serial_number(1)
            .not_valid_before(agora).not_valid_after(agora + dt.timedelta(days=1))
            .sign(chave, hashes.SHA256()))
    caminho.write_bytes(pkcs12.serialize_key_and_certificates(
        b"ficticio", chave, cert, None, BestAvailableEncryption(senha.encode())))
    return caminho


def test_carrega_com_a_senha_certa(tmp_path):
    caminho = _pfx(tmp_path / "Ficticio.pfx", "certa")
    certificado = carregar_certificado(caminho, {"ficticio": "certa"})
    assert (certificado.nome, certificado.senha) == ("Ficticio", "certa")


def test_senha_errada_recusa_antes_do_navegador(tmp_path):
    caminho = _pfx(tmp_path / "Ficticio.pfx", "certa")
    with pytest.raises(CertificadoIndisponivel, match="não abre"):
        carregar_certificado(caminho, {"ficticio": "errada"})


def test_sem_senha_recusa(tmp_path):
    caminho = _pfx(tmp_path / "Ficticio.pfx", "certa")
    with pytest.raises(CertificadoIndisponivel, match="sem senha"):
        carregar_certificado(caminho, {})
