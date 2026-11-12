# Atlas AI

Agente de IA que recebe tarefas em linguagem natural, escolhe ferramentas,
executa ações, observa os resultados e responde ao usuário.

Construído com **Python 3.11+, LangGraph, LangChain, Gemini, FastAPI e Pydantic**.

> Projeto de portfólio em evolução. Esta é a primeira versão (MVP): um único
> agente com três ferramentas, exposto por uma API HTTP.

## Funcionalidades

- Loop de agente (raciocinar → agir → observar) implementado com `StateGraph` do LangGraph
- *Tool calling* nativo do Gemini
- Ferramentas:
  - `calculator` – calculadora segura (sem `eval`; análise de AST com lista branca)
  - `get_current_datetime` – data, hora e dia da semana em qualquer fuso IANA
  - `generate_report` – grava relatórios `.txt` em um diretório isolado
- Limite configurável de iterações do agente
- Validação de entrada com Pydantic e tratamento de erros com códigos HTTP adequados
- 63 testes automatizados que **não precisam de chave de API**

## Estrutura

```
app/
├── main.py            # cria a aplicação FastAPI e os tratadores de erro
├── config.py          # configurações via variáveis de ambiente
├── llm.py             # criação do modelo Gemini
├── api/
│   ├── routes.py      # GET /health, POST /chat
│   ├── schemas.py     # modelos Pydantic de entrada/saída
│   └── dependencies.py
├── agent/
│   ├── graph.py       # grafo LangGraph (loop do agente)
│   ├── service.py     # executa o grafo e trata erros
│   └── prompts.py
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

A documentação interativa fica em http://localhost:8000/docs.

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

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

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
| `DEFAULT_TIMEZONE` | `America/Sao_Paulo` | Fuso padrão da ferramenta de data |
| `REPORTS_DIR` | `reports` | Diretório onde os relatórios são gravados |
| `MAX_MESSAGE_LENGTH` | `2000` | Tamanho máximo da mensagem do usuário |
| `LOG_LEVEL` | `INFO` | Nível de log |

## Segurança

- Nenhuma chave no código: apenas variáveis de ambiente / `.env` (ignorado pelo git).
- Nenhuma execução de código ou comando fornecido pelo usuário.
- Acesso a arquivos restrito ao diretório de relatórios, com nomes gerados pelo servidor.
- Número de iterações do agente limitado.
- Erros internos não são expostos ao cliente.

Detalhes em [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Próximos passos

- Memória de conversa (checkpointer do LangGraph + `thread_id`)
- Streaming de respostas
- Interface web responsiva
- Endpoint para listar e baixar relatórios gerados
- Observabilidade (tracing das execuções)

## Licença

Defina a licença do projeto antes de publicá-lo (por exemplo, MIT).
