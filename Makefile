# 注意：本工作区路径含冒号（F:\deepseek），PYTHONPATH 会被截断，
# 所以不使用 export PYTHONPATH，而是逐个进入子项目（各自的 pyproject 已配 pythonpath=["."]）。

PROJECTS := geo-radar filing-lens audit-loop cruxline agent-inbox agent-store

.PHONY: test demo clean

test:
	@for p in $(PROJECTS); do \
		echo "== $$p"; \
		( cd $$p && python3 -m pytest -q ) || exit 1; \
	done

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
