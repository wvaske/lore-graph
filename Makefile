.PHONY: up down schema test extract-demo lint
up:           ; docker compose up -d
down:         ; docker compose down
schema:       ; @cat schema/lore_graph_schema.cypher | docker exec -i lore-graph-neo4j cypher-shell -u neo4j -p "$${NEO4J_PASSWORD:-change-me}"
test:         ; pip install -e . -q && pytest -q
extract-demo: ; python -m lore_graph.extraction
lint:         ; ruff check lore_graph tests
