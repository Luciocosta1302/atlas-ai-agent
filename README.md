# Atlas AI

[![CI](https://github.com/Luciocosta1302/atlas-ai-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Luciocosta1302/atlas-ai-agent/actions/workflows/ci.yml)

Agente de IA que recebe tarefas em linguagem natural, escolhe ferramentas,
executa ações, observa os resultados e responde ao usuário.

Construído com **Python 3.11+, LangGraph, LangChain, Gemini, FastAPI e Pydantic**.

> Projeto de portfólio em evolução: um único agente com três ferramentas,
> memória persistente, streaming, interface web responsiva e controles de segurança.

## Funcionalidades

- Loop de agente (raciocinar → agir → observar) implementado com `StateGraph` do LangGraph
- *Tool calling* nativo do Gemini
- Ferramentas:
  - `calculator` – calculadora segura (sem `eval`; análise de AST com lista branca)
  - `get_current_datetime` – data, hora e dia da semana em qualquer fuso IANA
  - `generate_report` – grava relatórios `.txt` em um diretório isolado
- Limite configurável de iterações do agente
- Memória de conversa persistente em SQLite, com expiração automática
- Streaming das respostas via Server-Sent Events (`POST /chat/stream`)
- Interface web responsiva (claro/escuro), sem dependências de front-end
- Validação de entrada com Pydantic e tratamento de erros com códigos HTTP adequados
- Token de acesso, limite de requisições, CSP e cabeçalhos de segurança
- 101 testes automatizados que **não precisam de chave de API**

## Estrutura

```
app/
├── main.py            # cria a aplicação FastAPI e os tratadores de erro
├── config.py          # configurações via variáveis de ambiente
├── llm.py             # criação do modelo Gemini
├── memory.py          # memória persistente (SQLite) e expiração de conversas
├── security.py        # token, limite de requisições, cabeçalhos
├── api/
│   ├── routes.py      # /, /health, /chat, /chat/stream, /threads
│   ├── schemas.py     # modelos Pydantic de entrada/saída
│   └── dependencies.py
├── agent/
│   ├── graph.py       # grafo LangGraph (loop do agente)
│   ├── service.py     # executa o grafo e trata erros
│   └── prompts.py
├── static/
│   ├── index.html     # interface web
│   ├── app.js
│   └── app.css
└── tools/
    ├── calculator.py
    ├── datetime_tool.py
    └── report.py
tests/                 # pytest + modelo falso (tests/fakes.py)
docs/ARCHITECTURE.md   # arquitetura e decisões técnicas
```

## Como executar

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # Windows: copy .env.example .env
# edite .env e preencha GEMINI_API_KEY (https://aistudio.google.com/apikey)

uvicorn app.main:app --reload
```

- Interface web: http://localhost:8000
- Documentação interativa da API: http://localhost:8000/docs

## Endpoints

| Método | Rota | Descrição |
| --- | --- | --- |
| `GET` | `/` | Interface web |
| `GET` | `/health` | Verificação de saúde |
| `POST` | `/chat` | Executa uma tarefa e devolve a resposta completa |
| `POST` | `/chat/stream` | Mesma tarefa, com eventos SSE em tempo real |
| `DELETE` | `/threads/{thread_id}` | Apaga o histórico de uma conversa |

### Exemplo

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Quanto é (1250 * 12) * 0.15? Gere um relatório com o resultado."}'
```

Formato da resposta:

```json
{
  "answer": "texto final gerado pelo modelo",
  "iterations": 3,
  "tool_calls": [
    {"name": "calculator", "args": {"expression": "(1250 * 12) * 0.15"}, "output": "2250.0"},
    {"name": "generate_report", "args": {"title": "...", "content": "..."}, "output": "Relatório salvo como '...'."}
  ]
}
```

`tool_calls` mostra quais ferramentas o agente usou, com quais argumentos e o
que cada uma retornou, o que facilita depurar e explicar o comportamento do agente.

### Memória de conversa

Envie o `thread_id` recebido para continuar a mesma conversa:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "E quanto é isso por ano?", "thread_id": "<thread_id da resposta anterior>"}'
```

- As conversas ficam em `data/atlas.db` (SQLite) e **sobrevivem a reinícios**.
- Só o servidor cria `thread_id`s (128 bits aleatórios). Um id desconhecido,
  expirado ou apagado devolve **404**: o cliente não consegue inventar ou adivinhar
  o id de outra conversa.
- Conversas sem uso há mais de `CONVERSATION_TTL_HOURS` (padrão: 72 h) são apagadas
  automaticamente; `DELETE /threads/{thread_id}` apaga na hora.

### Streaming

`POST /chat/stream` recebe o mesmo corpo e responde com `text/event-stream`:

```
event: tool_call
data: {"name": "calculator", "args": {"expression": "50400 * 0.15"}}

event: tool_result
data: {"name": "calculator", "output": "7560.0"}

event: token
data: {"text": "15% do que você ganha por ano é "}

event: done
data: {"answer": "...", "thread_id": "...", "iterations": 2, "tool_calls": [...]}
```

Se algo falhar durante a execução, chega um evento `error` com `{"detail": "..."}`.

## Testes

```bash
pip install -r requirements-dev.txt
pytest

# lint e formatação
ruff check .
ruff format --check .
```

O GitHub Actions roda o lint e os testes (Python 3.11, 3.12 e 3.13) a cada push na `main` e em cada pull request.

Os testes usam um modelo de chat falso (`tests/fakes.py`) que devolve respostas
roteirizadas, inclusive chamadas de ferramenta. Assim o grafo real é exercitado
sem acesso à rede e sem chave de API.

## Configuração

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `GEMINI_API_KEY` | — | Chave da API do Gemini (obrigatória para `/chat`) |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Modelo do Gemini (veja os disponíveis no [AI Studio](https://aistudio.google.com)) |
| `GEMINI_TEMPERATURE` | — | Opcional; os modelos Gemini mais novos ignoram este parâmetro |
| `LLM_TIMEOUT_SECONDS` | `60` | Timeout das chamadas ao modelo |
| `AGENT_MAX_ITERATIONS` | `5` | Máximo de chamadas ao modelo por requisição (1–20) |
| `MAX_HISTORY_MESSAGES` | `30` | Mensagens recentes da conversa enviadas ao modelo |
| `DEFAULT_TIMEZONE` | `America/Sao_Paulo` | Fuso padrão da ferramenta de data |
| `REPORTS_DIR` | `reports` | Diretório onde os relatórios são gravados |
| `MAX_MESSAGE_LENGTH` | `2000` | Tamanho máximo da mensagem do usuário |
| `LOG_LEVEL` | `INFO` | Nível de log |
| `DATABASE_PATH` | `data/atlas.db` | Arquivo SQLite da memória |
| `CONVERSATION_TTL_HOURS` | `72` | Conversas inativas por mais tempo são apagadas |
| `ATLAS_API_TOKEN` | — | Token exigido em `Authorization: Bearer` (mín. 16 caracteres). Vazio = API aberta |
| `RATE_LIMIT_PER_MINUTE` | `20` | Requisições por minuto por cliente nas rotas protegidas |
| `MAX_REQUEST_BYTES` | `64000` | Tamanho máximo do corpo da requisição |

## Segurança

- Nenhuma chave no código: apenas variáveis de ambiente / `.env` (ignorado pelo git).
- Nenhuma execução de código ou comando fornecido pelo usuário.
- Acesso a arquivos restrito ao diretório de relatórios, com nomes gerados pelo servidor.
- Número de iterações do agente limitado.
- Erros internos não são expostos ao cliente.
- **Token de acesso** (`ATLAS_API_TOKEN`) para `/chat`, `/chat/stream` e `/threads`,
  comparado em tempo constante. A interface web pede o token quando necessário.
  Sem token, a API fica aberta e um aviso aparece no log.
- **Limite de requisições** por cliente (429 + `Retry-After`), para proteger a cota do Gemini.
- **`thread_id` gerado só pelo servidor**; ids desconhecidos devolvem 404.
- **Retenção limitada**: conversas inativas são apagadas (privacidade/LGPD).
- **Cabeçalhos de segurança** (`nosniff`, `X-Frame-Options`, `Referrer-Policy`) e
  **CSP estrita** na interface (sem scripts inline ou de outros domínios).
- Corpo da requisição limitado (413) e consultas SQL sempre parametrizadas.

Para expor o servidor na internet: defina `ATLAS_API_TOKEN`, use HTTPS (proxy reverso)
e rode o uvicorn com `--proxy-headers` para o limite de requisições enxergar o IP real.

Detalhes em [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Próximos passos

- Avaliação automática da escolha de ferramentas
- Deploy público (ex.: Render ou Railway)
- Contas de usuário (cada conversa ligada a um dono)
- Endpoint para listar e baixar relatórios gerados
- Observabilidade (tracing das execuções)

## Licença

[MIT](LICENSE)
