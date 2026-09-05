.PHONY: check test viewer

check:
	python3 -m compileall -q simulation scripts viewer tests
	for script in scripts/*.sh; do bash -n "$$script"; done
	git diff --check

test:
	python3 -m unittest discover -s tests -v
	python3 -m unittest discover -s viewer -p 'test_*.py' -v
	node viewer/test_app.js

viewer:
	./scripts/serve_viewer.sh
