# Verificação de Pagamento PER/DCOMP — eCAC (Python, desktop)

Recebe a planilha de PER/DCOMPs já protocolados (pelas automações de
Protocolação de Restituição e de Ressarcimento) e, para cada um, abre uma
**Declaração de Compensação** no e-CAC para verificar se o PER/DCOMP já foi
pago pela Receita. O resultado vai para a planilha.

> ⚠️ **O "Enviar" transmite uma Declaração de Compensação de verdade.** Com
> `PERMITIR_ACOES_REAIS_NO_ECAC = False` (`VerificacaoPagamento/config.py`, o
> padrão) a automação faz tudo até "O Documento está apto para envio" e **para
> sem clicar "Enviar"; nada é gravado na planilha**. Para rodar de verdade,
> troque para `True`.

## Como rodar

```bat
pip install -r requirements.txt
copy .env.example .env      &rem e preencha GEMINI_API_KEY (captcha do gov.br)
python run.py
```

O formulário pede a planilha e um **limite de linhas** (vem com 3; em branco =
todas as pendentes).

## Planilha (primeira aba)

Layout da aba "pis cofins": cabeçalho na linha 1, dados a partir da 2.
Usadas hoje: **B Procurador** (escolhe o certificado), **D CNPJ** (perfil no
e-CAC), **K Tributo**, **M PERDCOMP** (24 dígitos), **Z Status** e **AA
Situação da Verificação** (saída; **qualquer texto na AA tira a linha** das
próximas execuções). B1, D1 e
M1 são conferidos antes do login.

Entram no lote, por enquanto:
- status (Z) **"Análise concluída"** (`STATUS_Z_A_PROCESSAR`);
- tributo (K) **PIS** ou **COFINS**, com variantes ("PIS/PASEP", "COFINS/FASE"…);
  o resto ("2024", "PIS/COFINS"…) vira aviso;
- procurador diferente de **ELIANE** (`PROCURADORES_IGNORADOS`, só aparece no log).

## Certificados

Um `.pfx` por procurador em `C:\Certificados`, senhas em
`C:\Certificados\senhas.json` (mesmo esquema do VerificaMensagensPagamento).
O nome da coluna B casa com o `.pfx` **exatamente** (sem caixa/acento) ou pela
tabela `APELIDOS_CERTIFICADO` em `config.py` — nunca por semelhança. A senha
é testada antes de abrir o navegador. Linhas sem certificado viram um aviso
agregado no resumo.

## Fluxo

1. Lê a planilha, monta o lote: **certificado > empresa > linhas**.
2. Para cada certificado, **um navegador**: login já no perfil da 1ª empresa;
   entre as empresas, só troca de perfil. Ao terminar todas: "Sair com
   Segurança", fecha, próximo certificado. Procuração recusada pula só a empresa.
3. **O perfil ativo é conferido** ao entrar em cada empresa (`#informacao-perfil`
   do e-CAC: "Procurador de: <CNPJ>") e de novo antes de cada documento. Motivo:
   o `ecac_login` procura o popup de mensagens importantes ANTES de trocar e,
   se acha, devolve sucesso sem ter trocado.
4. **Mensagens importantes** (popup `#dialog-bloqueio-ativo-caixapostal`): a
   empresa é processada normalmente (pelo link do PER/DCOMP não bloqueia), e no
   fim dela: Caixa Postal → Sair com Segurança → fecha → login novo para a
   próxima empresa.
5. Para cada linha: módulo PER/DCOMP → "Novo Documento" → **"Declaração de
   Compensação"** → Retificador **"Não"** → Tipo de Crédito pela coluna K →
   Apelido "Verificação Pagamento PER" → "Outra Qualificação" → "O crédito já
   foi detalhado em PER/DCOMP anterior" → nº da coluna M (campo com máscara,
   digitado e conferido) → **"Prosseguir"** (conferindo que a tela avançou).
6. Termo de inconstitucionalidade "Não" + OK → não litígio ✔ → Crédito Original
   10,00 → **Informar Débito** (COFINS / próprio contribuinte / 5856-01 /
   10/2026 / 25/11/2026 / R$ 0,01 → Confirmar) → CPF do responsável → Prosseguir.
   Valores fixos em `config.py`.
7. **"O Documento está apto para envio"?**
   - não: AA = `Documento não apto, não possível verificar`;
   - sim: Prosseguir → **Enviar**, e o desfecho:
     - "…TEVE O PAGAMENTO REALIZADO…" → AA = `Pagamento realizado`;
     - "A TRANSMISSÃO NÃO FOI CONCLUÍDA" por outro motivo → AA = a mensagem da
       Receita, inteira;
     - "Declaração foi enviada com sucesso" → AA = `Pagamento não realizado,
       protocolação feita` (o número vai para o diário e o resumo) → OK;
     - popup de "pendências não impeditivas" no meio do caminho → "Não" (não
       revisar) e a transmissão segue;
     - nada disso em 3 min, ou o navegador caiu → AA = `Verificar no e-CAC
       (envio sem confirmação)`. **Nenhuma execução reenvia essa linha**: confira
       no e-CAC. Com 3 dessas na mesma execução, ela para.
8. Próxima linha direto pelo "Novo Documento" (recarrega o módulo só depois de
   erro ou tela inesperada).

## Onde ficam os resultados

- **Diário** `resultados/<planilha>_verificacao.csv`: cada resultado é gravado
  em disco **na hora** — inclusive a tentativa de envio, ANTES do clique. Se o
  robô cair entre o clique e o desfecho, a linha vira "Verificar no e-CAC" na
  próxima execução e nunca é reenviada.
- **Coluna AA da planilha**: gravada em lote (a cada 10 resultados ou 10 min, e
  no fim), porque abrir+salvar a planilha real leva ~24 s (aba "inss" com 1 milhão
  de linhas). **Deixe a planilha fechada no Excel** durante a execução. Se não
  der para gravar, nada se perde: o diário é aplicado na próxima execução.
- **Cópia de segurança** da planilha em `backups/` antes da primeira gravação de
  cada execução.

### O clique em "Declaração de Compensação"

Os 5 radios têm o mesmo `id`/`name` e nenhum `value`. O alvo é
`label.radio-inline:has(i.icon-radio[data-value='3'])`, conferido pelo texto.
O que já travou as irmãs foi o `.ui-widget-overlay` do PrimeNG interceptando o
clique, e o duplo clique piorava. Então a automação espera o rótulo ficar no
topo da tela, clica uma vez e confere (radio marcado e "Documento
Retificador?" na tela). Só se a tela não reagir ela tenta a próxima
estratégia: `input.click()` via JS, depois o evento direto. Quando algo foge
do esperado, a tela é salva em `debug_telas/`.

## Testes

```bat
python -m pytest tests -q
python -m ruff check .
```

Os testes `tests/test_*_navegador.py` abrem um **Chrome real** (headless)
contra réplicas do HTML das telas: overlay, tela antiga escondida, data-value
renumerado, e a Declaração inteira até cada desfecho do envio. São pulados se
o Chrome não abrir.
