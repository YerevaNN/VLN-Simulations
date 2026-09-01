.PHONY: check viewer

check:
	python3 -m py_compile simulation/*.py viewer/app.py
	bash -n scripts/*.sh
	git diff --check

viewer:
	./scripts/serve_viewer.sh
