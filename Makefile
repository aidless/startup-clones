# 注意：本工作区路径含冒号（F:\deepseek），PYTHONPATH 会被截断，
# 所以不使用 export PYTHONPATH，而是逐个进入子项目（各自的 pyproject 已配 pythonpath=["."]）。

PROJECTS := geo-radar filing-lens audit-loop cruxline agent-inbox agent-store console

.PHONY: test demo clean matrix matrix-record e2e

test:
	@for p in $(PROJECTS); do \
		echo "== $$p"; \
		( cd $$p && python3 -m pytest -q ) || exit 1; \
	done

# 全语料解析矩阵（22 份 10-K，约 2 分钟）：改解析器后跑一次，看有没有文件读不通
matrix:
	python3 scripts/corpus_matrix.py --baseline docs/corpus-matrix.json

# 改过解析器后重记基线（会覆盖 docs/corpus-matrix.json，再跑 make matrix 复核）
matrix-record:
	python3 scripts/corpus_matrix.py --record docs/corpus-matrix.json

# 七个项目端到端串联（真跑子进程，约 40 秒）
e2e:
	python3 scripts/e2e.py

console:
	cd console && python3 app.py --port 8800

serve:
	cd filing-lens && python3 app/server.py

demo:
	@( cd geo-radar     && python3 -m georadar.cli demo )
	@( cd filing-lens   && python3 -m filinglens.cli demo )
	@( cd audit-loop    && python3 -m auditloop.cli demo )
	@( cd cruxline      && python3 -m cruxline.cli demo )
	@( cd agent-inbox   && python3 -m agentinbox.cli demo )
	@( cd agent-store   && python3 -m agentstore.cli demo )

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache */out
