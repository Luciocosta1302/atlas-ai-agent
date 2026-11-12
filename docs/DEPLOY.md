# Deploy do Atlas AI

O projeto tem um `Dockerfile` (funciona em qualquer plataforma que rode containers)
e um `render.yaml`, que cria o serviço no [Render](https://render.com) com poucos cliques.

## Render (plano gratuito)

Funciona pelo navegador, inclusive no celular.

1. Acesse https://dashboard.render.com e entre com a sua conta do **GitHub**.
2. Clique em **New** → **Blueprint**.
3. Conecte o repositório `atlas-ai-agent` (autorize o acesso do Render, se pedir).
4. O Render lê o `render.yaml` e mostra o serviço `atlas-ai`. Preencha:
   - **GEMINI_API_KEY**: a sua chave do Google AI Studio.
   - O `ATLAS_API_TOKEN` é gerado automaticamente; não precisa preencher.
5. Clique em **Apply** / **Deploy Blueprint** e aguarde o build (alguns minutos).
6. Quando o status ficar **Live**, abra a URL do serviço
   (algo como `https://atlas-ai-xxxx.onrender.com`).
7. Para usar a interface, pegue o token em **atlas-ai → Environment →
   ATLAS_API_TOKEN** (ícone de olho) e cole quando a página pedir.

Testando pela linha de comando:

```bash
curl -X POST https://SEU-SERVICO.onrender.com/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer SEU_TOKEN" \
  -d '{"message": "Quanto é 15% de 3000?"}'
```

### Limitações do plano gratuito do Render

| Limitação | Efeito no Atlas AI |
| --- | --- |
| O serviço "dorme" após ~15 min sem acesso | A primeira requisição depois disso demora cerca de 1 minuto. |
| Disco temporário (apagado ao dormir, reiniciar ou fazer novo deploy) | As conversas (SQLite) e os relatórios são perdidos nesses momentos. A memória funciona enquanto o serviço está ativo. |

Para memória realmente persistente no Render, use uma instância paga com
**Persistent Disk** montado em `/app/data` (o banco fica em `data/atlas.db`,
relativo a `/app`). Outra opção é trocar o checkpointer por PostgreSQL.

## Segurança em produção

- **Mantenha o `ATLAS_API_TOKEN` definido.** Sem ele, qualquer pessoa com a URL
  usaria a sua cota do Gemini. Compartilhe o token só com quem deve testar
  (ex.: recrutadores) e gere outro se ele vazar.
- **Limites de requisições**: `RATE_LIMIT_PER_MINUTE` (por cliente) e
  `GLOBAL_RATE_LIMIT_PER_MINUTE` (todos juntos). O limite global é o que
  realmente protege a cota: no Render, o proxy repassa o `X-Forwarded-For` enviado
  pelo cliente sem filtrá-lo, então a aplicação **não** usa esse cabeçalho (ele
  poderia ser forjado para escapar do limite). Por isso, atrás do proxy todos os
  clientes compartilham o limite "por cliente".
- **HTTPS**: o Render já entrega a URL com HTTPS.
- **Chave do Gemini**: fica só nas variáveis de ambiente do Render. No plano
  gratuito do Gemini não há cobrança; se você ativar o faturamento no Google,
  configure alertas de gasto.

## Outras plataformas (Docker)

Qualquer serviço que rode containers (Railway, Fly.io, Google Cloud Run, uma VPS…)
pode usar o `Dockerfile`. A aplicação escuta na porta da variável `PORT`
(padrão 8000).

```bash
docker build -t atlas-ai .
docker run -p 8000:8000 \
  -e GEMINI_API_KEY=sua_chave \
  -e ATLAS_API_TOKEN=um_token_com_pelo_menos_16_caracteres \
  -v atlas-data:/app/data \
  atlas-ai
```

O volume `atlas-data` mantém as conversas entre reinícios do container.
