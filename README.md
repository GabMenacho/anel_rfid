# Anel RFID &mdash; pagina de produtos (GitHub Pages)

Esta pasta e o site que o anel consulta pela internet: um arquivo
`produtos.json` com os dados de cada produto (nome, cor, marca e o
caminho do audio) e uma pasta `audio/` com os arquivos `.wav`/`.mp3`
correspondentes. Tambem inclui:

- `index.html` &mdash; catalogo publico (so leitura) para conferir o que esta cadastrado.
- `admin/index.html` &mdash; painel para cadastrar/editar/remover produtos e subir os audios, direto do navegador.

## 1. Criar o repositorio no GitHub

1. Crie um repositorio novo (pode ser publico ou privado), ex.: `anel-rfid-produtos`.
2. Suba o conteudo desta pasta (`produtos.json`, `index.html`, `admin/`, `audio/`) para a raiz do repositorio, no branch `main`.

## 2. Ativar o GitHub Pages

1. No repositorio, vá em **Settings &rarr; Pages**.
2. Em "Build and deployment", escolha **Deploy from a branch**.
3. Branch: `main`, pasta: `/ (root)`. Salve.
4. Em alguns minutos o GitHub mostra a URL do site, algo como:
   `https://SEU_USUARIO.github.io/anel-rfid-produtos/`

## 3. Criar um token de acesso (para o painel conseguir salvar)

O GitHub Pages so serve arquivos (nao tem "banco de dados"), entao o
painel em `/admin/` grava os cadastros fazendo commits no proprio
repositorio atraves da API do GitHub. Para isso ele precisa de um token:

1. No GitHub: **Settings (da sua conta) &rarr; Developer settings &rarr; Personal access tokens &rarr; Fine-grained tokens &rarr; Generate new token**.
2. Em "Repository access", escolha **Only select repositories** e selecione o repositorio `anel-rfid-produtos`.
3. Em "Permissions &rarr; Repository permissions", defina **Contents: Read and write**.
4. Gere o token e copie (ele so e mostrado uma vez).

> O token fica guardado **somente no seu navegador** (localStorage) e e
> enviado direto para `api.github.com` &mdash; nunca passa por nenhum
> servidor externo. Ainda assim, trate-o como uma senha: nao o compartilhe
> e revogue-o se achar que foi exposto.

## 4. Cadastrar produtos

1. Acesse `https://SEU_USUARIO.github.io/anel-rfid-produtos/admin/`.
2. Preencha repositorio (`usuario/repo`), branch (`main`) e o token; clique em **Salvar e carregar produtos**.
3. No formulario abaixo, preencha o UID da tag (use `descobrir_uid()` no
   firmware para ler o UID real de cada tag), nome, cor, marca e envie o
   arquivo de audio gravado para esse produto.
4. Clique em **Salvar produto**. Isso faz dois commits automaticos no
   repositorio: um subindo o audio em `audio/`, outro atualizando
   `produtos.json`. O GitHub Pages atualiza o site em ~1 minuto.

Repita para cada produto. Para editar ou remover, use os botoes na
tabela de produtos cadastrados.

## 5. Apontar o anel para esta pagina

No arquivo `anel_rfid_v2.py` (firmware), ajuste:

```python
WIFI_SSID = "SUA_REDE"
WIFI_SENHA = "SUA_SENHA"
BASE_URL = "https://SEU_USUARIO.github.io/anel-rfid-produtos"
```

O anel vai buscar `BASE_URL/produtos.json` ao ligar, e baixar (e guardar
em cache na flash) o audio de cada produto na primeira vez que a tag
correspondente for aproximada.
