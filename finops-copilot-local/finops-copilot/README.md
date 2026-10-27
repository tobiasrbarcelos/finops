# Azure FinOps Copilot (execução local)

## Como rodar (Windows)
Pré-requisitos: **Python 3.11+** e **Node 20+** instalados.

1. Duplo clique em `1-iniciar-backend.bat` e deixe a janela aberta.
2. Duplo clique em `2-iniciar-frontend.bat` (outra janela). O navegador abre em http://localhost:3000.
3. Login: `admin@finops.app` / `finops-local-123` (só para uso local; troque em `backend/.env`).

No Cursor, use File → Open Folder e abra esta pasta; os dois `.bat` também rodam pelo terminal (Ctrl+J).

## Dados
- Na primeira subida o backend cria dados de exemplo (mock).
- Para dados reais: Configuração → cadastre o Service Principal e clique em "Salvar & sincronizar".
  Permissões: Reader + Cost Management Reader + Monitoring Reader nas subscriptions (dev, hml, prd).
- O banco padrão é em memória: ao reiniciar o backend os dados somem (o mock volta sozinho; o Service
  Principal precisa ser cadastrado de novo). Para persistir, instale o MongoDB e troque o `MONGO_URL`
  em `backend/.env` por `mongodb://localhost:27017`.

## Ambientes (dev / hml / prd)
Cada subscription pertence a um ambiente. O sistema infere pelo nome (palavra inteira: dev, hml, prd, prod...);
o que não casar fica "Não mapeado" e você corrige em Configuração → Subscriptions descobertas.

## Chat do copiloto
Desativado por padrão (dependia de uma chave do Emergent). O restante do sistema funciona normalmente.
